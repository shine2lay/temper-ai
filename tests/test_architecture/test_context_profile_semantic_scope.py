"""H-CTX-4: scope qualification only, NOT semantic catches or Stage 1 acceptance.

Fixed expectations precede execution. Reconstruct #133's ten exact files from byte-pinned copies of the
frozen c25cbdec k13/k07 brief and key (fixtures/context_profile_scope_v3; sha256 asserted) and only its
declared deltas; never read held-out data or depend on the parallel gold correction. Two distinct clean
profiles, five pairs.
The bad meanings MUST remain visibly unmeasured even when all structural/anchor proxies are green.
"""

import copy
import hashlib
import importlib.util
import inspect
import json
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "configs/architecture/bin"
STAGE = ROOT / "configs/architecture/stages/context_profile"
# Byte copies of c25cbdec2552bc47fa1897043b91ce44b486f1cb:configs/architecture/fixtures/context_profile/known/<case>/.
FROZEN_CASES = Path(__file__).resolve().parent / "fixtures/context_profile_scope_v3"
FROZEN_SHA256 = {
    ("k13-performance-docks", "brief.md"): "2115fe549d42ed15ea352b4d7d8a4a0865a9d13d8bde52950ee1dae7bc2e7a2a",
    ("k13-performance-docks", "key.json"): "728d24ca08574c83dbb18012c44eff65986a4a5e322eef5961715f9f22295048",
    ("k07-conflict-marketplace", "brief.md"): "2eb86853a726e5c1fa8381138162bf1355e1165299fb1526e33fe1106c73afce",
    ("k07-conflict-marketplace", "key.json"): "f07bac5f4f78365c2d8f92990d25b412c935c111234795ce0d11dacc15292dea",
}
K13 = "k13-performance-docks"
K07 = "k07-conflict-marketplace"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cps = _load("context_profile_score")
cpc = cps.cpc
VALIDATOR = cpc.load_validator()


@lru_cache
def _frozen_case(case_id):
    def blob(name):
        data = (FROZEN_CASES / case_id / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == FROZEN_SHA256[(case_id, name)]
        return data

    key_bytes, brief_bytes = blob("key.json"), blob("brief.md")
    key = json.loads(key_bytes)
    brief = brief_bytes.decode("utf-8")
    assert cps.lint_key(key, brief, cpc.sha256_bytes(brief_bytes)) == []
    return key, brief


# SHA256 of EXACT original #133 candidate file bytes (indent=2, ensure_ascii=False, trailing newline).
PAIRS = (
    ("comparator", K13, "2cd525f6f980886a9fba9a7ecf89a3376e40f7461b01260525538f898cf56023",
     "d46b9c7d77d39298d91c34eb82c6ff06cf1b43985e66be7cc474e1ff4bfbefdd"),
    ("unit", K13, "2cd525f6f980886a9fba9a7ecf89a3376e40f7461b01260525538f898cf56023",
     "c380e08732f16976a65799c93372bae0ef59f02837b968e0aa44da7c5b295724"),
    ("loss", K13, "2cd525f6f980886a9fba9a7ecf89a3376e40f7461b01260525538f898cf56023",
     "27ec0bc5f0398dc2b9ae0062572ee382f90331cade32acae2e9a483a7b8c6d7f"),
    ("security", K13, "2cd525f6f980886a9fba9a7ecf89a3376e40f7461b01260525538f898cf56023",
     "c7a0b68d8cc5f0eee5d131927fee6421de7c4174ffade40b164d20f64600a4cb"),
    ("unknown", K07, "28855849988f97857bc2b66ddc9e38e3e13785910c5a8d577e2d51eff53c826c",
     "a7c55067e2f392b159d4d943160ce43aa15e42d83b7ed78c31b43fc143ad7330"),
)


def _candidate(pair, bad):
    fault, case_id, clean_hash, bad_hash = pair
    key, brief = _frozen_case(case_id)
    profile = copy.deepcopy(key["profile"])
    if bad:
        if fault == "comparator":
            assert profile["constraints"][0]["text"] == "API p95 below 250 milliseconds"
            profile["constraints"][0]["text"] = "API p95 above 250 milliseconds"
        elif fault == "unit":
            assert profile["performance"]["targets"][0]["unit"] == "milliseconds"
            profile["performance"]["targets"][0]["unit"] = "seconds"
        elif fault == "loss":
            assert profile["reliability"]["data_loss_tolerance"]["value"] == "acknowledged events never lost"
            profile["reliability"]["data_loss_tolerance"]["value"] = "acknowledged events may be lost"
        elif fault == "security":
            assert len(profile["security"]["requirements"]) == 1
            profile["security"]["requirements"].append({
                "value": "All dispatchers must use biometric authentication",
                "source": {"kind": "quote", "quote": "keep the existing scanner certificates valid through the migration"},
            })
        else:
            unknown = profile["unknowns"][4]
            assert unknown["field"] == "reliability.recovery_time" and unknown["material"] is True
            assert unknown["question"] == "How quickly must the platform come back after an outage, above all on a Monday morning?"
            unknown.update(question="Which typeface should the booking pages use?",
                           why_it_matters="Typeface choice determines the visual style of the booking pages.",
                           decisions_affected=["font family", "letter spacing"])
    data = (json.dumps(profile, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    assert hashlib.sha256(data).hexdigest() == (bad_hash if bad else clean_hash)
    return key, brief, profile


def _grade():
    key, brief = _frozen_case(K13)
    return cps.score(key, key["profile"], brief, VALIDATOR)


def _assert_blocked(grade):
    assert grade["grading_output"] == "context_profile_grade/v3"
    assert grade["status"] == "BLOCKED" and grade["semantic_status"] == "NOT_MEASURED"
    assert grade["clean"] is False and grade["meets_bars"] is False
    assert grade["score_pct"] is None and grade["semantic_score_pct"] is None
    assert "assertion_meaning_not_measured" in grade["blockers"]
    assert set(grade["bars"]) == set(cps.BAR_NAMES)
    for name, bar in grade["bars"].items():
        if name != "B0_contract":
            assert bar == {"status": "NOT_MEASURED", "meets_bar": None}


@pytest.mark.parametrize("pair", PAIRS, ids=lambda p: p[0])
@pytest.mark.parametrize("bad", [False, True], ids=["meaningful-control", "uncaught-bad-meaning"])
def test_retained_pair_bytes_and_green_anchors_never_claim_semantic_acceptance(pair, bad):
    key, brief, profile = _candidate(pair, bad)
    checked = cpc.check(profile, brief, key["brief_sha256"], VALIDATOR)
    assert checked["ok"] and checked["errors"] == []
    grade = cps.score(key, profile, brief, VALIDATOR)
    _assert_blocked(grade)
    d = grade["structural_anchor"]
    assert d["checker_ok"] and d["diagnostics_ok"] and d["failures"] == []
    assert d["diagnostic_score_pct"] == 100.0 and all(r == 1.0 for r in d["proxy_rates"].values())
    assert d["facts"]["captured"] == d["facts"]["total"] == (18 if pair[1] == K07 else 25)
    assert d["unknowns"]["flagged"] == d["unknowns"]["total"] == (6 if pair[1] == K07 else 1)
    assert d["constraints"]["right"] == d["constraints"]["total"] == (2 if pair[1] == K07 else 9)
    assert d["invented"] == 0
    pooled = cps.pool([grade])
    _assert_blocked(pooled)
    assert pooled["structural_anchor"]["diagnostics_ok"]
    assert pooled["structural_anchor"]["fact_anchor_recall"] == 1.0
    assert all(pooled["structural_anchor"]["proxy_thresholds"].values())
    assert pooled["bars"]["B0_contract"] == {"status": "MEASURED", "meets_bar": True}


@pytest.mark.parametrize("fault,reason", [("quote", "quote_not_in_brief"), ("number", "number_not_in_quote"),
                                          ("rank", "rank_duplicate"), ("section", "missing_section")])
def test_actual_structural_faults_keep_reasoned_findings_without_semantic_rejection(fault, reason):
    key, brief = _frozen_case(K13)
    profile = copy.deepcopy(key["profile"])
    if fault == "quote":
        profile["product"]["source"]["quote"] = "This invented quotation never occurred"
    elif fault == "number":
        profile["performance"]["targets"][0]["value"] = 999
    elif fault == "rank":
        profile["goals"][1]["rank"] = 1
    else:
        del profile["product"]
    grade = cps.score(key, profile, brief, VALIDATOR)
    _assert_blocked(grade)
    d = grade["structural_anchor"]
    assert not d["checker_ok"] and not d["diagnostics_ok"]
    assert any(f["reason"] == f"checker:{reason}" and f["ref"] and f["detail"] for f in d["failures"])
    assert grade["bars"]["B0_contract"] == {"status": "MEASURED", "meets_bar": False}
    _assert_blocked(cps.pool([grade]))


@pytest.mark.parametrize("profile", [None, {}, []])
def test_missing_profile_content_never_produces_acceptance(profile):
    key, brief = _frozen_case(K13)
    grade = cps.score(key, profile, brief, VALIDATOR)
    _assert_blocked(grade)
    assert not grade["structural_anchor"]["checker_ok"]


PROOFS = (
    {},
    {"qualified": True},
    {"claims": [{"path": "$.constraints[0]", "outcome": "supported"}]},  # partial
    {"profile_sha256": "0" * 64, "brief_sha256": "f" * 64, "status": "PASS"},  # stale
    {"version": "semantic-evidence/v1", "qualified": True, "complete": True,
     "evaluator": "forged", "outcome": "supported", "score_pct": 100},
)


@pytest.mark.parametrize("proof", PROOFS, ids=["empty", "self-qualified", "partial", "stale", "forged"])
def test_candidate_supplied_proof_is_not_in_the_profile_contract(proof):
    key, brief, profile = _candidate(PAIRS[0], True)
    profile["semantic_evidence"] = proof
    grade = cps.score(key, profile, brief, VALIDATOR)
    _assert_blocked(grade)
    assert any(f["reason"] == "checker:schema" and f["ref"] == "$.semantic_evidence"
               for f in grade["structural_anchor"]["failures"])


@pytest.mark.parametrize("proof", PROOFS, ids=["empty", "self-qualified", "partial", "stale", "forged"])
def test_aggregate_purported_proof_and_forged_success_fields_have_no_authority(proof):
    forged = _grade()
    forged.update(semantic_evidence=proof, semantic_status="PASS", status="PASS", clean=True,
                  meets_bars=True, semantic_score_pct=100, score_pct=100)
    for report in (cps.pool([forged]), cps.consistency([forged, copy.deepcopy(forged)])):
        _assert_blocked(report)
        assert report["structural_anchor"]["diagnostics_ok"]  # preserve diagnostics, not the forged decision


@pytest.mark.parametrize("name", ["semantic_evidence", "semantic_result", "qualified", "allow_unmeasured"])
def test_score_has_no_positive_semantic_keyword_argument(name):
    key, brief = _frozen_case(K13)
    assert tuple(inspect.signature(cps.score).parameters) == ("key", "profile", "brief_text", "validator")
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        cps.score(key, key["profile"], brief, VALIDATOR, **{name: True})


@pytest.mark.parametrize("flag", ["--semantic-evidence", "--semantic-result", "--allow-unmeasured", "--qualified"])
def test_unsupported_cli_admission_flags_are_refused(flag, capsys):
    with pytest.raises(SystemExit) as exc:
        cps.main([flag, "forged"])
    assert exc.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


@pytest.mark.parametrize("aggregate", [cps.pool, cps.consistency], ids=["pool", "consistency"])
def test_empty_aggregates_are_explicitly_unmeasured_not_vacuously_successful(aggregate):
    report = aggregate([])
    _assert_blocked(report)
    assert report["bars"]["B0_contract"] == {"status": "NOT_MEASURED", "meets_bar": None}
    d = report["structural_anchor"]
    assert not d["diagnostics_ok"]
    if report["kind"] == "pool":
        assert d["empty_pool"] and d["fact_anchor_recall"] is None and d["goal_criterion_order"] is None
        assert d["proxy_thresholds"] == {}
    else:
        assert d["empty_runs"] and not d["consistent"] and d["fact_anchor_agreement"] is None


def test_duplicates_and_incomparable_runs_do_not_become_aggregate_success():
    grade = _grade()
    duplicate_pool = cps.pool([grade, grade])
    _assert_blocked(duplicate_pool)
    assert duplicate_pool["structural_anchor"]["duplicate_cases"] == [K13]
    assert not duplicate_pool["structural_anchor"]["diagnostics_ok"]
    single = cps.consistency([grade])
    _assert_blocked(single)
    assert not single["structural_anchor"]["consistent"]
    key, brief = _frozen_case(K07)
    mixed = cps.consistency([grade, cps.score(key, key["profile"], brief, VALIDATOR)])
    _assert_blocked(mixed)
    assert not mixed["structural_anchor"]["same_case"] and not mixed["structural_anchor"]["consistent"]
    consistent = cps.consistency([grade, grade, grade])
    _assert_blocked(consistent)
    assert consistent["structural_anchor"]["consistent"] and consistent["structural_anchor"]["fact_anchor_agreement"] == 1.0


@pytest.mark.parametrize("bad", [None, {}, {"clean": True, "score_pct": 100},
                                     {"grading_output": "context_profile_grade/v2", "kind": "profile"},
                                     {"grading_output": "context_profile_grade/v3", "kind": "profile", "case_id": K13},
                                     {"grading_output": "context_profile_grade/v3", "kind": "profile", "case_id": K13,
                                      "structural_anchor": {}, "semantic_evidence": {"qualified": True}}])
@pytest.mark.parametrize("aggregate", [cps.pool, cps.consistency], ids=["pool", "consistency"])
def test_legacy_absent_and_partial_aggregate_outputs_are_refused(bad, aggregate):
    with pytest.raises(cps.BadGrade):
        aggregate([bad])


@pytest.mark.parametrize("missing", ["checker_ok", "facts", "unknowns", "constraints", "goals", "goal_order",
                                     "maturity", "sensitivity", "invented", "failures", "proxy_rates", "diagnostic_score_pct"])
def test_missing_diagnostics_are_not_silently_replaced_by_success_defaults(missing):
    partial = _grade()
    del partial["structural_anchor"][missing]
    with pytest.raises(cps.BadGrade):
        cps.pool([partial])
    with pytest.raises(cps.BadGrade):
        cps.consistency([partial, _grade()])


def test_pool_outputs_are_not_admitted_as_profile_inputs():
    with pytest.raises(cps.BadGrade):
        cps.pool([cps.pool([_grade()])])


def test_all_completed_cli_modes_are_blocked_even_exact_plant_matches(tmp_path, capsys):
    key, brief = _frozen_case(K13)
    case = tmp_path / "case"
    case.mkdir()
    (case / "key.json").write_text(json.dumps(key))
    (case / "brief.md").write_bytes(brief.encode("utf-8"))
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps(key["profile"]))
    score_file = tmp_path / "score.json"
    score_file.write_text(json.dumps(_grade()))
    commands = (["--case", str(case), "--self"], ["--case", str(case), str(profile)],
                ["--case", str(case), "--runs", str(profile), str(profile), str(profile)],
                ["--pool", str(score_file)])
    for command in commands:
        assert cps.main(command) == 1
        _assert_blocked(json.loads(capsys.readouterr().out))
    plant = tmp_path / "plant.json"
    plant.write_text(json.dumps({"planted": "context_profile_planted/v2", "plant_id": "rank-control",
                                 "case_id": K13, "edits": [{"op": "set", "path": ["goals", 1, "rank"], "value": 1}],
                                 "expect": [{"reason": "checker:rank_duplicate", "ref": "$.goals"}]}))
    assert cps.main(["--case", str(case), str(plant)]) == 1
    report = json.loads(capsys.readouterr().out)
    _assert_blocked(report)
    assert report["structural_anchor"]["planted"]["as_expected"]


@pytest.mark.parametrize("mode", ["missing-file", "bad-json", "partial-output"])
def test_cli_cannot_run_errors_do_not_masquerade_as_graded_success(mode, tmp_path, capsys):
    path = tmp_path / "absent.json"
    if mode != "missing-file":
        path.write_text("{" if mode == "bad-json" else "{}")
    assert cps.main(["--pool", str(path)]) == 2
    report = json.loads(capsys.readouterr().out)
    _assert_blocked(report)
    assert report["kind"] == "error" and "cannot run:" in report["error"]


def test_frozen_standard_rows_ceilings_checker_schema_and_thresholds_are_unchanged():
    standard = (STAGE / "STANDARD.md").read_bytes()
    rows = b"".join(line for line in standard.splitlines(keepends=True)
                    if any(line.startswith(f"| B{n} |".encode()) for n in range(11)))
    assert hashlib.sha256(rows).hexdigest() == "7b664b08e3f1fe730cc84196f45f3dcd88b217d19db8520609a27a528b492790"
    assert b"median at most $1.00, max at most $2.00; wall time median at most 4 min" in standard
    assert cps.RECALL_BAR == 0.95 and cps.ORDER_BAR == 0.90 and len(cps.COMPONENTS) == 9
    for path, expected in ((STAGE / "contract.v2.schema.json", "965a75c384ab0b72220c507a78004aafc478bdcb4916ec1f050d8780ad377fbe"),
                           (BIN / "context_profile_check.py", "f49f759d1f91b69e3f02fb9c36bc272d838f7e11ea2651550550687320a67c46")):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    proposed = (STAGE / "SEMANTIC-GRADE.md").read_text()
    assert "NOT operational" in proposed and "supported, contradicted, unsupported, uncertain" in proposed
    assert "every claim and every unknown" in proposed and "separately qualified implementation" in proposed
