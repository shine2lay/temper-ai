"""The context-profile stage's checker, scorer, known cases and planted profiles (System architecture, #122).

configs/architecture/stages/context_profile/STANDARD.md freezes what the stage must produce (contract v1)
and how it is measured. These tests hold the deterministic parts to it before any model stage exists:
- the checker passes clean profiles and fails each planted fault with its expected reason;
- every known case's key lints clean, passes the checker and scores 100% against itself;
- every planted bad profile causes exactly the failures it names, no more and no fewer;
- the scorer's run comparison (bar B5) and pooling (bars B0-B4, B7-B10) behave.
Standard library only, no model, no server.
"""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ARCH = ROOT / "configs" / "architecture"
BIN = ARCH / "bin"
STAGE = ARCH / "stages" / "context_profile"
FIXTURES = ARCH / "fixtures" / "context_profile"
KNOWN = sorted(p for p in (FIXTURES / "known").iterdir() if p.is_dir())
PLANTED = sorted((FIXTURES / "planted").glob("*.json"))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cpc = _load("context_profile_check")
cps = _load("context_profile_score")
VALIDATOR = cpc.load_validator()


def _case(case_id: str) -> tuple[dict, str]:
    folder = FIXTURES / "known" / case_id
    key, brief, _sha = cps.load_case(folder)
    return key, brief


def _reasons(report: dict) -> set[str]:
    return {e["reason"] for e in report["errors"]}


def _check(profile: dict, brief: str, key: dict) -> dict:
    return cpc.check(profile, brief, key["brief_sha256"], VALIDATOR)


# ---------------------------------------------------------------- the contract and the case set

def test_the_schema_loads_and_its_unknown_fields_match_the_scorer():
    schema = json.loads((STAGE / "contract.v1.schema.json").read_text())
    enum = schema["$defs"]["unknown"]["properties"]["field"]["enum"]
    assert sorted(enum) == sorted(cps.UNKNOWN_FIELDS) and len(enum) == len(set(enum))
    assert tuple(schema["$defs"]["goal"]["properties"]["criterion"]["enum"]) == cpc.CRITERIA
    assert tuple(schema["properties"]["maturity"]["properties"]["stage"]["enum"]) == cpc.STAGES


def test_the_standard_names_every_known_case():
    standard = (STAGE / "STANDARD.md").read_text()
    for folder in KNOWN:
        assert folder.name in standard


def test_the_known_cases_cover_every_category_once_with_briefs_of_the_right_length():
    assert len(KNOWN) >= 12
    categories = []
    for folder in KNOWN:
        key = json.loads((folder / "key.json").read_text())
        assert key["case_id"] == folder.name
        categories.append(key["category"])
        words = len((folder / "brief.md").read_text().split())
        assert 300 <= words <= 1500, f"{folder.name}: {words} words"
    assert sorted(categories) == sorted(cps.CATEGORIES)


@pytest.mark.parametrize("folder", KNOWN, ids=lambda p: p.name)
def test_every_key_passes_the_checker_and_scores_100_against_itself(folder):
    key, brief, sha = cps.load_case(folder)  # raises BrokenKey when the key does not lint clean
    checked = cpc.check(key["profile"], brief, sha, VALIDATOR)
    assert checked["ok"], checked["errors"]
    result = cps.score(key, key["profile"], brief, VALIDATOR)
    assert result["clean"], result["failures"]
    assert result["score_pct"] == 100.0
    assert result["facts"]["total"] >= 8 and result["constraints"]["total"] >= 1 and result["goals"]["total"] >= 3


# ---------------------------------------------------------------- planted profiles

def test_there_are_at_least_ten_planted_profiles_over_at_least_four_cases():
    plants = [json.loads(p.read_text()) for p in PLANTED]
    assert len(plants) >= 10
    assert len({p["case_id"] for p in plants}) >= 4
    assert len({p["plant_id"] for p in plants}) == len(plants)


@pytest.mark.parametrize("path", PLANTED, ids=lambda p: p.stem)
def test_every_planted_profile_causes_exactly_its_expected_failures(path):
    document = json.loads(path.read_text())
    assert document["plant_id"] == path.stem
    key, brief = _case(document["case_id"])
    profile, plant = cps.unwrap(document, key["profile"])
    result = cps.score(key, profile, brief, VALIDATOR)
    verdict = cps.against_plant(result, plant)
    assert verdict["as_expected"], verdict
    assert not result["clean"]


def test_a_planted_edit_that_does_not_fit_the_profile_is_refused():
    key, _brief = _case("k02-startup-invoicing")
    with pytest.raises(cps.BadPlant):
        cps.apply_edits(key["profile"], [{"op": "set", "path": ["goals", 9, "rank"], "value": 1}])
    with pytest.raises(cps.BadPlant):
        cps.apply_edits(key["profile"], [{"op": "move", "path": ["goals"]}])
    edited = cps.apply_edits(key["profile"], [{"op": "remove", "path": ["goals", 0]}])
    assert len(edited["goals"]) == len(key["profile"]["goals"]) - 1
    assert len(key["profile"]["goals"]) == 3  # the base is not changed


# ---------------------------------------------------------------- checker faults, one at a time

@pytest.fixture
def k02():
    key, brief = _case("k02-startup-invoicing")
    return key, brief, copy.deepcopy(key["profile"])


def test_a_clean_profile_passes_and_whitespace_in_quotes_is_normalised(k02):
    key, brief, profile = k02
    assert _check(profile, brief, key)["ok"]
    quote = profile["workload"]["observed"][0]["source"]["quote"]
    profile["workload"]["observed"][0]["source"]["quote"] = quote.replace(" ", "\n  ", 1)
    assert _check(profile, brief, key)["ok"]


def test_a_fabricated_quote_fails(k02):
    key, brief, profile = k02
    profile["product"]["source"]["quote"] = "Ledgerly is the market leader in invoicing"
    assert _reasons(_check(profile, brief, key)) == {"quote_not_in_brief"}


def test_a_number_its_quote_does_not_hold_fails_unless_it_is_an_assumption(k02):
    key, brief, profile = k02
    profile["workload"]["observed"][0]["value"] = 150
    assert _reasons(_check(profile, brief, key)) == {"number_not_in_quote"}
    profile = copy.deepcopy(key["profile"])
    profile["team"]["operating_capacity"].append(
        {"value": "about 40 hours of support a week", "source": {"kind": "assumption", "why": "derived from the team size"}})
    assert _check(profile, brief, key)["ok"]


def test_duplicate_and_gapped_ranks_fail(k02):
    key, brief, profile = k02
    profile["goals"][2]["rank"] = 2
    assert "rank_duplicate" in _reasons(_check(profile, brief, key))
    profile = copy.deepcopy(key["profile"])
    profile["goals"][2]["rank"] = 5
    assert _reasons(_check(profile, brief, key)) == {"rank_gap"}


def test_a_constraint_duplicated_as_a_goal_fails(k02):
    key, brief, profile = k02
    constraint = profile["constraints"][0]
    profile["goals"].append({"id": "G4", "criterion": "security", "rank": 4, "note": "card data",
                             "source": copy.deepcopy(constraint["source"])})
    assert _reasons(_check(profile, brief, key)) == {"constraint_goal_overlap"}


def test_a_missing_section_fails(k02):
    key, brief, profile = k02
    del profile["budget"]
    assert "missing_section" in _reasons(_check(profile, brief, key))


def test_a_wrong_maturity_value_fails(k02):
    key, brief, profile = k02
    profile["maturity"]["stage"] = "seed"
    assert "bad_enum" in _reasons(_check(profile, brief, key))


def test_a_stage_without_evidence_fails_and_unknown_needs_none(k02):
    key, brief, profile = k02
    profile["maturity"]["evidence"] = []
    assert _reasons(_check(profile, brief, key)) == {"maturity_without_evidence"}
    profile["maturity"]["stage"] = "unknown"
    assert _check(profile, brief, key)["ok"]


def test_invented_observed_workload_fails(k02):
    key, brief, profile = k02
    profile["workload"]["observed"].append({"what": "API calls", "value": 50, "unit": "per second",
                                            "source": {"kind": "assumption", "why": "a usual rate for this size"}})
    assert _reasons(_check(profile, brief, key)) == {"observed_not_quoted"}


def test_short_quotes_wrong_hashes_duplicate_ids_and_unknown_keys_fail(k02):
    key, brief, profile = k02
    profile["product"]["source"]["quote"] = "Ledgerly"
    assert "quote_too_short" in _reasons(_check(profile, brief, key)) | _reasons(_check(profile, brief, key))
    profile = copy.deepcopy(key["profile"])
    profile["brief_sha256"] = "0" * 64
    assert _reasons(_check(profile, brief, key)) == {"brief_hash_mismatch"}
    profile = copy.deepcopy(key["profile"])
    profile["constraints"][1]["id"] = profile["constraints"][0]["id"]
    assert _reasons(_check(profile, brief, key)) == {"duplicate_id"}
    profile = copy.deepcopy(key["profile"])
    profile["owner_mood"] = "happy"
    assert _reasons(_check(profile, brief, key)) == {"schema"}


# ---------------------------------------------------------------- scorer faults, one at a time

def _failures(key: dict, profile: dict, brief: str) -> set[tuple[str, str]]:
    return {(f["reason"], f["ref"]) for f in cps.score(key, profile, brief, VALIDATOR)["failures"]}


def test_a_mandatory_privacy_requirement_as_a_tradeable_goal_fails():
    key, brief = _case("k05-small-therapy")
    profile = copy.deepcopy(key["profile"])
    hipaa = profile["constraints"].pop(0)
    profile["goals"].append({"id": "G4", "criterion": "privacy", "rank": 4, "note": "HIPAA", "source": hipaa["source"]})
    assert _failures(key, profile, brief) == {("constraint_as_goal", "C1")}


def test_a_missing_material_unknown_and_one_not_marked_material_fail():
    key, brief = _case("k07-conflict-marketplace")
    profile = copy.deepcopy(key["profile"])
    profile["unknowns"].pop(0)
    assert _failures(key, profile, brief) == {("unknown_not_flagged", "U1")}
    profile = copy.deepcopy(key["profile"])
    profile["unknowns"][0]["material"] = False
    assert _failures(key, profile, brief) == {("unknown_not_material", "U1")}


def test_an_assumption_filling_a_field_the_brief_leaves_open_is_invented():
    key, brief = _case("k08-missing-volunteers")
    profile = copy.deepcopy(key["profile"])
    profile["budget"]["run_monthly"] = {"value": "free tier", "source": {"kind": "assumption", "why": "charities get free hosting"}}
    result = cps.score(key, profile, brief, VALIDATOR)
    assert {(f["reason"], f["ref"]) for f in result["failures"]} == {("guessed_unknown", "budget.run_monthly")}
    assert result["invented"] == 1 and result["rates"]["no_invention"] == 0.0


def test_a_forecast_used_as_observed_workload_is_caught_by_its_trap():
    key, brief = _case("k09-projected-fitness")
    profile = copy.deepcopy(key["profile"])
    profile["maturity"]["evidence"].append(
        {"value": "2 million workout logs a month", "source": {"kind": "quote", "quote": "processes 2 million workout logs a month"}})
    assert _failures(key, profile, brief) == {("trap:projected_as_observed", "T1")}


def test_a_missed_fact_and_a_wrong_goal_order_fail():
    key, brief = _case("k06-large-simple-transit")
    profile = copy.deepcopy(key["profile"])
    profile["workload"]["peaks"].pop(1)  # the snow-day peak
    profile["goals"][0]["rank"], profile["goals"][1]["rank"] = 2, 1
    reasons = {r for r, _ref in _failures(key, profile, brief)}
    assert reasons == {"fact_missed", "goal_order"}


# ---------------------------------------------------------------- several runs, the pool, the key lint, the CLI

def test_runs_that_agree_are_consistent_and_a_changed_maturity_is_not():
    key, brief = _case("k03-growing-scheduling")
    same = [cps.score(key, key["profile"], brief, VALIDATOR) for _ in range(3)]
    assert cps.consistency(same)["consistent"]
    other = copy.deepcopy(key["profile"])
    other["maturity"]["stage"] = "startup"
    report = cps.consistency(same[:2] + [cps.score(key, other, brief, VALIDATOR)])
    assert not report["consistent"] and report["differs"] == ["maturity"]


def test_the_keys_pooled_meet_every_bar_and_a_planted_run_does_not():
    results = [cps.score(k, k["profile"], b, VALIDATOR) for k, b, _ in (cps.load_case(f) for f in KNOWN)]
    pooled = cps.pool(results)
    assert pooled["meets_bars"] and pooled["fact_recall"] == 1.0 and pooled["invented"] == 0
    plant = json.loads((FIXTURES / "planted" / "p01-k05-hipaa-as-goal.json").read_text())
    key, brief = _case(plant["case_id"])
    bad = cps.score(key, cps.unwrap(plant, key["profile"])[0], brief, VALIDATOR)
    pooled = cps.pool([r for r in results if r["case_id"] != plant["case_id"]] + [bad])
    assert not pooled["meets_bars"]
    assert [name for name, ok in pooled["bars"].items() if not ok] == ["B4_constraints_classified"]


def test_a_broken_key_is_refused():
    folder = FIXTURES / "known" / "k01-idea-pantry"
    key = json.loads((folder / "key.json").read_text())
    brief_bytes = (folder / "brief.md").read_bytes()
    sha = cpc.sha256_bytes(brief_bytes)
    assert cps.lint_key(key, brief_bytes.decode(), sha) == []
    broken = copy.deepcopy(key)
    broken["facts"][0]["anchors"] = ["words that are nowhere in the brief"]
    broken["goals"][0]["rank"] = 7
    problems = cps.lint_key(broken, brief_bytes.decode(), sha)
    assert any("is not in the brief" in p for p in problems)
    assert any("ranks must be 1 to n" in p for p in problems)
    assert cps.lint_key(key, brief_bytes.decode(), "f" * 64)


def test_the_command_lines_exit_codes(tmp_path, capsys):
    folder = FIXTURES / "known" / "k04-large-photos"
    assert cpc.main(["--brief", str(folder / "brief.md"), str(folder / "key.json")]) == 0
    assert cps.main(["--case", str(folder), "--self"]) == 0
    bad = json.loads((folder / "key.json").read_text())["profile"]
    bad["goals"][0]["rank"] = 9
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad))
    assert cpc.main(["--brief", str(folder / "brief.md"), str(path)]) == 1
    assert cps.main(["--case", str(folder), str(path)]) == 1
    path.write_text("{ not json")
    assert cps.main(["--case", str(folder), str(path)]) == 2
    plant = PLANTED[0]
    case = json.loads(plant.read_text())["case_id"]
    assert cps.main(["--case", str(FIXTURES / "known" / case), str(plant)]) == 0
    capsys.readouterr()
