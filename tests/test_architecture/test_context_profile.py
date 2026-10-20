"""The context-profile stage's checker, scorer, known cases and plants (Architecture, #122; v2 #127).

configs/architecture/stages/context_profile/STANDARD.md freezes what the stage must produce (contract v2)
and how it is measured. These tests hold the deterministic parts to it before any model stage exists:
- the checker passes clean profiles and fails each planted fault with its expected reason;
- every known case's key lints clean, passes the checker and has 100% structural/anchor diagnostics;
- every planted bad profile causes exactly the failures it names, no more and no fewer;
- structural/anchor run comparison and pooling preserve their observations without semantic acceptance.
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
    schema = json.loads((STAGE / "contract.v2.schema.json").read_text())
    enum = schema["$defs"]["unknown"]["properties"]["field"]["enum"]
    assert sorted(enum) == sorted(cps.UNKNOWN_FIELDS) and len(enum) == len(set(enum))
    assert tuple(schema["$defs"]["goal"]["properties"]["criterion"]["enum"]) == cpc.CRITERIA
    assert tuple(schema["properties"]["maturity"]["properties"]["stage"]["enum"]) == cpc.STAGES


def test_case_content_is_in_the_known_readme_not_the_standard_or_schema():
    readme = (FIXTURES / "known" / "README.md").read_text()
    documents = [(STAGE / name).read_text() for name in ("STANDARD.md", "contract.v2.schema.json")]
    assert not (STAGE / "contract.v1.schema.json").exists()
    for folder in KNOWN:
        assert folder.name in readme
        for document in documents:
            assert folder.name not in document
    standard = documents[0]
    assert "H-CTX-1" in standard and "H-CTX-2" in standard and "## v2 changes and why" in standard


def test_the_known_cases_cover_every_category_once_with_briefs_of_the_right_length():
    assert len(KNOWN) == 14
    categories = []
    for folder in KNOWN:
        key = json.loads((folder / "key.json").read_text())
        assert key["case_id"] == folder.name
        categories.append(key["category"])
        words = len((folder / "brief.md").read_text().split())
        assert 300 <= words <= 1500, f"{folder.name}: {words} words"
        if folder.name.startswith(("k13-", "k14-")):
            assert words <= 500 and key["traps"], folder.name
    assert sorted(categories) == sorted(cps.CATEGORIES)


@pytest.mark.parametrize("folder", KNOWN, ids=lambda p: p.name)
def test_every_key_passes_the_checker_and_has_100_diagnostic_percent_against_itself(folder):
    key, brief, sha = cps.load_case(folder)  # raises BrokenKey when the key does not lint clean
    checked = cpc.check(key["profile"], brief, sha, VALIDATOR)
    assert checked["ok"], checked["errors"]
    grade = cps.score(key, key["profile"], brief, VALIDATOR)
    result = grade["structural_anchor"]
    assert result["diagnostics_ok"], result["failures"]
    assert result["diagnostic_score_pct"] == 100.0
    assert result["facts"]["total"] >= 8 and result["constraints"]["total"] >= 1 and result["goals"]["total"] >= 3
    assert grade["semantic_status"] == "NOT_MEASURED" and not grade["clean"]


# ---------------------------------------------------------------- planted profiles

def test_there_are_nineteen_planted_profiles_over_at_least_four_cases():
    plants = [json.loads(p.read_text()) for p in PLANTED]
    assert len(plants) == 19
    assert all(p["planted"] == "context_profile_planted/v2" for p in plants)
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
    assert not result["structural_anchor"]["diagnostics_ok"]


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
    assert _reasons(_check(profile, brief, key)) == {"unknown_field_unnamed"}
    profile["unknowns"].append({"field": "maturity.stage", "question": "What stage is this?",
                                "why_it_matters": "Demand trend is not settled.", "material": True,
                                "decisions_affected": ["growth planning"]})
    assert _check(profile, brief, key)["ok"]


def test_invented_observed_workload_fails(k02):
    key, brief, profile = k02
    profile["workload"]["observed"].append({"what": "API calls", "value": 50, "unit": "per second",
                                            "source": {"kind": "assumption", "why": "a usual rate for this size"}})
    assert _reasons(_check(profile, brief, key)) == {"observed_not_quoted"}


def test_short_quotes_wrong_hashes_duplicate_ids_and_unknown_keys_fail(k02):
    key, brief, profile = k02
    profile["product"]["source"]["quote"] = "Ledgerly"
    assert _reasons(_check(profile, brief, key)) == {"quote_too_short"}
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
    return {(f["reason"], f["ref"]) for f in cps.score(key, profile, brief, VALIDATOR)["structural_anchor"]["failures"]}


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
    result = cps.score(key, profile, brief, VALIDATOR)["structural_anchor"]
    assert {(f["reason"], f["ref"]) for f in result["failures"]} == {("guessed_unknown", "budget.run_monthly")}
    assert result["invented"] == 1 and result["proxy_rates"]["no_invention"] == 0.0


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
    assert cps.consistency(same)["structural_anchor"]["consistent"]
    other = copy.deepcopy(key["profile"])
    other["maturity"]["stage"] = "startup"
    report = cps.consistency(same[:2] + [cps.score(key, other, brief, VALIDATOR)])["structural_anchor"]
    assert not report["consistent"] and report["differs"] == ["maturity"]


def test_the_keys_pooled_meet_proxy_thresholds_and_a_planted_run_does_not():
    results = [cps.score(k, k["profile"], b, VALIDATOR) for k, b, _ in (cps.load_case(f) for f in KNOWN)]
    grade = cps.pool(results)
    pooled = grade["structural_anchor"]
    assert pooled["diagnostics_ok"] and pooled["fact_anchor_recall"] == 1.0 and pooled["invention_signals"] == 0
    assert not grade["meets_bars"] and grade["semantic_status"] == "NOT_MEASURED"
    plant = json.loads((FIXTURES / "planted" / "p01-k05-hipaa-as-goal.json").read_text())
    key, brief = _case(plant["case_id"])
    bad = cps.score(key, cps.unwrap(plant, key["profile"])[0], brief, VALIDATOR)
    grade = cps.pool([r for r in results if r["case_id"] != plant["case_id"]] + [bad])
    pooled = grade["structural_anchor"]
    assert not grade["meets_bars"] and not pooled["diagnostics_ok"]
    assert [name for name, ok in pooled["proxy_thresholds"].items() if not ok] == ["constraint_anchor_classification"]


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
    assert cps.main(["--case", str(folder), "--self"]) == 1
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
    assert cps.main(["--case", str(FIXTURES / "known" / case), str(plant)]) == 1
    capsys.readouterr()


# ---------------------------------------------------------------- v2: four review gaps, their boundaries and controls

@pytest.mark.parametrize("folder", KNOWN, ids=lambda p: p.name)
def test_every_v2_key_records_stage_quotes_sections_and_why_silence_is_not_material(folder):
    key, brief, _sha = cps.load_case(folder)
    for stage in key["maturity"]["accepted"]:
        assert stage["stage"] in cpc.STAGES
        for quote in stage["quotes"]:
            assert 2 <= len(cpc.norm(quote).split()) <= 40
            assert cpc.norm(quote) in cpc.norm(brief)
    for fact in key["facts"]:
        assert "in" not in fact and fact["primary"] in cps.FACT_SECTIONS
        assert ("alt" in fact) == bool(fact.get("why_alt"))
        assert len(cps.fact_sections(fact)) <= 2
    material = {u.get("field") for u in key["unknowns"]}
    for field in key["fields_unknown"]:
        assert (field["field"] in material) != bool(field.get("not_material_reason"))


@pytest.mark.parametrize("stage", ["scaled", "large"])
def test_scale_and_organisation_labels_are_not_lifecycle_stages(k02, stage):
    key, brief, profile = k02
    profile["maturity"]["stage"] = stage
    assert _reasons(_check(profile, brief, key)) == {"bad_enum"}


def test_maturity_is_rederived_from_demand_not_age_size_or_governance():
    key, _brief = _case("k02-startup-invoicing")
    assert cps.accepted_stages(key) == ["established"]
    key, _brief = _case("k06-large-simple-transit")
    assert cps.accepted_stages(key) == ["established"]
    for case in ("k04-large-photos", "k11-privacy-reading", "k12-internal-expenses"):
        key, _brief = _case(case)
        assert cps.accepted_stages(key) == ["unknown"]
        unknown = next(u for u in key["profile"]["unknowns"] if u.get("field") == "maturity.stage")
        rationale = next(f for f in key["fields_unknown"] if f["field"] == "maturity.stage")
        assert unknown["why_it_matters"] and not unknown["material"] and rationale["not_material_reason"]


@pytest.mark.parametrize("section", ["current_system", "external_systems", "performance"])
def test_the_new_sections_are_required(k02, section):
    key, brief, profile = k02
    del profile[section]
    assert _reasons(_check(profile, brief, key)) == {"missing_section"}


@pytest.mark.parametrize("kind", ["absent", "assumption"])
def test_a_known_current_system_state_requires_a_quote(kind):
    key, brief = _case("k13-performance-docks")
    profile = copy.deepcopy(key["profile"])
    if kind == "absent":
        del profile["current_system"]["source"]
    else:
        profile["current_system"]["source"] = {"kind": "assumption", "why": "a working guess about the system"}
    assert _reasons(_check(profile, brief, key)) == {"current_system_not_quoted"}


def test_an_external_system_cannot_borrow_another_systems_quote():
    key, brief = _case("k13-performance-docks")
    profile = copy.deepcopy(key["profile"])
    profile["external_systems"][0]["name"] = "InventedGateway"
    checked = _check(profile, brief, key)
    assert _reasons(checked) == {"system_name_not_in_quote"}
    assert cps.score(key, profile, brief, VALIDATOR)["structural_anchor"]["invented"] == 1


def test_a_performance_number_has_to_be_in_its_own_quote():
    key, brief = _case("k13-performance-docks")
    profile = copy.deepcopy(key["profile"])
    profile["performance"]["targets"][0]["value"] = 999
    assert _reasons(_check(profile, brief, key)) == {"number_not_in_quote"}


def test_mandatory_performance_targets_are_constraints_and_speed_is_not_efficiency():
    key, _brief = _case("k13-performance-docks")
    assert len(key["profile"]["performance"]["targets"]) == 3
    quotes = [cpc.norm(c["source"]["quote"]) for c in key["profile"]["constraints"]]
    for target in key["profile"]["performance"]["targets"]:
        quote = cpc.norm(target["source"]["quote"])
        assert any(quote in c or c in quote for c in quotes)
    assert [g["criterion"] for g in key["profile"]["goals"]][:2] == ["performance", "efficiency"]


@pytest.mark.parametrize("length,reason", [(1, "quote_too_short"), (2, None), (40, None), (41, "quote_too_long")])
def test_the_quote_length_boundaries(k02, length, reason):
    key, brief, profile = k02
    # A real span from the brief, no invented quote; summary states no number.
    profile["product"]["summary"] = "product under review"
    profile["product"]["source"]["quote"] = " ".join(brief.split()[10:10 + length]) if length > 1 else "Ledgerly"
    assert _reasons(_check(profile, brief, key)) == ({reason} if reason else set())


@pytest.mark.parametrize("field", cpc.UNKNOWN_SCALARS)
def test_every_unknown_scalar_needs_its_own_path(k02, field):
    key, brief, profile = k02
    node = profile
    parts = field.split(".")
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = "unknown"
    profile["unknowns"] = [u for u in profile["unknowns"] if u.get("field") != field]
    checked = _check(profile, brief, key)
    assert [(e["reason"], e["path"]) for e in checked["errors"]] == [("unknown_field_unnamed", f"$.{field}")]
    profile["unknowns"].append({"field": field, "question": "What is left unstated?", "material": False,
                                "why_it_matters": "No choice turns on this field for this check.",
                                "decisions_affected": ["context review"]})
    assert _check(profile, brief, key)["ok"]


@pytest.mark.parametrize("field", ["external_systems", "current_system.items", "constraints", "goals",
                                   *cpc.MEASURES, *(f for f in cpc.LIST_FACTS if f != "maturity.evidence")])
def test_every_empty_fact_list_needs_its_own_path(k02, field):
    key, brief, profile = k02
    node = profile
    parts = field.split(".")
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = []
    profile["unknowns"] = [u for u in profile["unknowns"] if u.get("field") != field]
    checked = _check(profile, brief, key)
    assert [(e["reason"], e["path"]) for e in checked["errors"]] == [("unknown_field_unnamed", f"$.{field}")]


@pytest.mark.parametrize("field,ref", [("reliability.data_loss_tolerance", "U6"), ("reliability.recovery_time", "U5")])
def test_k07_loss_and_recovery_are_required_material_unknowns(field, ref):
    key, brief = _case("k07-conflict-marketplace")
    profile = copy.deepcopy(key["profile"])
    unknown = next(u for u in profile["unknowns"] if u.get("field") == field)
    unknown["material"] = False
    assert _check(profile, brief, key)["ok"]
    assert _failures(key, profile, brief) == {("unknown_not_material", ref)}


def test_unknown_matching_keeps_lexical_fallback_when_a_field_is_not_named():
    key, brief = _case("k07-conflict-marketplace")
    profile = copy.deepcopy(key["profile"])
    unknown = next(u for u in profile["unknowns"] if u.get("field") == "reliability.data_loss_tolerance")
    unknown["material"] = False
    profile["unknowns"].append({"question": "How much booking data loss can be tolerated?", "material": True,
                                "why_it_matters": "Durability choices depend on this answer.",
                                "decisions_affected": ["backups"]})
    assert not _failures(key, profile, brief)


def _matching_item(quote):
    return cpc.Item("team.skills", "$.team.skills[0]", {}, [quote]), cpc.norm(quote)


def test_maximum_matching_reassigns_an_earlier_fact_instead_of_greedy_undercredit():
    facts = [{"id": "F1", "anchors": ["alpha"], "primary": "team.skills"},
             {"id": "F2", "anchors": ["beta"], "primary": "team.skills"}]
    items = [_matching_item("alpha beta"), _matching_item("alpha alone")]
    matched, eligible = cps.match_facts(facts, items)
    assert eligible == [[0, 1], [0]]
    assert matched == {0: 1, 1: 0}
    assert cps.match_facts(facts, items[:1])[0] == {0: 0}  # first fact wins the tie
    assert cps.match_facts(facts, items)[0] == matched     # deterministic


@pytest.mark.parametrize("n,m", [(2, 3), (3, 2), (3, 3)])
def test_maximum_matching_cardinality_against_every_small_graph(n, m):
    from itertools import product

    facts = [{"id": f"F{i}", "anchors": [f"needle{i}"], "primary": "team.skills"} for i in range(n)]
    for bits in product((0, 1), repeat=n * m):
        edges = [[j for j in range(m) if bits[i * m + j]] for i in range(n)]
        quoted = [_matching_item(" ".join(f"needle{i}" for i in range(n) if j in edges[i])) for j in range(m)]
        best = max(sum(j >= 0 for j in assignment) for assignment in product(range(-1, m), repeat=n)
                   if len({j for j in assignment if j >= 0}) == sum(j >= 0 for j in assignment)
                   and all(j < 0 or j in edges[i] for i, j in enumerate(assignment)))
        matched, _eligible = cps.match_facts(facts, quoted)
        assert len(matched) == best, (edges, matched, best)
        assert len(set(matched.values())) == len(matched)


def test_a_padded_quote_can_credit_only_one_of_its_three_facts():
    key, brief = _case("k02-startup-invoicing")
    plant = json.loads((FIXTURES / "planted" / "p18-k02-padded-three-facts.json").read_text())
    profile, _header = cps.unwrap(plant, key["profile"])
    assert _check(profile, brief, key)["ok"]  # not a long-quote failure
    result = cps.score(key, profile, brief, VALIDATOR)["structural_anchor"]
    assert set(result["facts"]["captured_ids"]) & {"F1", "F2", "F3"} == {"F1"}
    assert result["facts"]["captured"] == result["facts"]["total"] - 2
    assert _failures(key, profile, brief) == {("fact_quote_shared", "F2"), ("fact_quote_shared", "F3")}


def test_duplicate_failures_do_not_disappear_when_checking_a_plants_exact_reasons():
    key, brief = _case("k02-startup-invoicing")
    result = cps.score(key, key["profile"], brief, VALIDATOR)
    plant = {"case_id": result["case_id"], "expect": [{"reason": "fault", "ref": "F1"}]}
    result["structural_anchor"]["failures"] = [{"reason": "fault", "ref": "F1"}] * 2
    verdict = cps.against_plant(result, plant)
    assert not verdict["as_expected"] and verdict["unexpected"] == [["fault", "F1"]]


def test_extra_material_unknowns_and_quote_lengths_are_report_only(k02):
    from statistics import median

    key, brief, profile = k02
    profile["unknowns"].append({"question": "Who approves accessible language translations?", "material": True,
                                "why_it_matters": "Translations change localisation choices.",
                                "decisions_affected": ["localisation"]})
    result = cps.score(key, profile, brief, VALIDATOR)["structural_anchor"]
    assert result["diagnostics_ok"] and result["diagnostic_score_pct"] == 100.0
    assert result["material_unknowns_not_in_key"] == [{"field": None, "question": "Who approves accessible language translations?"}]
    lengths = [len(cpc.norm(i.quote).split()) for i in cpc.iter_items(profile) if i.kind == "quote"]
    assert result["quote_words"] == {"median": median(lengths), "max": max(lengths)}
    profile["unknowns"][-1]["material"] = False
    assert cps.score(key, profile, brief, VALIDATOR)["structural_anchor"]["material_unknowns_not_in_key"] == []


@pytest.mark.parametrize("fault", ["no_primary", "legacy_in", "alt_without_why", "why_without_alt", "many_alternatives"])
def test_v2_key_sections_are_narrow_and_alternatives_are_justified(k02, fault):
    key, brief, _profile = k02
    broken = copy.deepcopy(key)
    fact = broken["facts"][0]
    if fault == "no_primary":
        del fact["primary"]
    elif fault == "legacy_in":
        fact["in"] = ["workload.observed", "maturity.evidence"]
    elif fault == "alt_without_why":
        del fact["why_alt"]
    elif fault == "why_without_alt":
        del fact["alt"]
    else:
        fact["alt"] = ["maturity.evidence", "team.size"]
    assert cps.lint_key(broken, brief, key["brief_sha256"])


def test_fields_unknown_requires_exactly_one_material_status_and_full_coverage(k02):
    key, brief, _profile = k02
    broken = copy.deepcopy(key)
    broken["fields_unknown"][0]["not_material_reason"] = "Not a decision."
    assert any("exactly one" in p for p in cps.lint_key(broken, brief, key["brief_sha256"]))
    broken = copy.deepcopy(key)
    del broken["fields_unknown"][-1]["not_material_reason"]
    assert any("exactly one" in p for p in cps.lint_key(broken, brief, key["brief_sha256"]))
    broken = copy.deepcopy(key)
    broken["fields_unknown"].pop()
    assert any("list exactly" in p for p in cps.lint_key(broken, brief, key["brief_sha256"]))


def test_v2_does_not_lower_a_bar_or_the_cost_and_time_ceilings():
    assert cps.RECALL_BAR == 0.95 and cps.ORDER_BAR == 0.90 and len(cps.COMPONENTS) == 9
    standard = (STAGE / "STANDARD.md").read_text()
    for bar in range(11):
        assert f"| B{bar} |" in standard
    assert "median at most $1.00, max at most $2.00; wall time median at most 4 min" in standard
    assert "3 runs per case consistent" in standard
