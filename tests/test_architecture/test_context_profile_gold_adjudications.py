"""H-CTX-5: two source-adjudicated gold corrections, not a semantic grader.

Only the public known k06/k07 briefs and keys are read. Fixed reference assertions
preserve the adjudications; lint/checker and exact anchor diagnostics exercise
contrasts. No clean/100, pool verdict or unmeasured semantic bar is evidence here.
"""

import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "configs" / "architecture" / "bin"
KNOWN = ROOT / "configs" / "architecture" / "fixtures" / "context_profile" / "known"
K06 = "k06-large-simple-transit"
K07 = "k07-conflict-marketplace"
PAST_FLAT = "these numbers have been flat for two years"
ASHFORD_QUOTE = (
    "Ashford's transit agency has invited us to add their city next year, "
    "which they say would bring about 400,000 more monthly users."
)
ASHFORD_PROJECTION = {
    "what": (
        "Ashford transit agency's conditional estimate if its invited city is added "
        "next year, not guaranteed or current traffic"
    ),
    "value": 400000,
    "unit": "additional monthly users (about)",
    "source": {"kind": "quote", "quote": ASHFORD_QUOTE},
}
RETENTION_QUESTION = {
    "question": (
        "How long should personal contact and booking data be retained, and what "
        "deletion or archive policy should apply to live data and backups?"
    ),
    "why_it_matters": (
        "No retention period or deletion policy is supplied. Plausible answers could "
        "change live-data deletion/archive, backup expiry and restore/re-deletion "
        "handling, plus storage cost; these are possible architecture effects, "
        "not stated rules or a chosen design."
    ),
    "decisions_affected": [
        "live-data deletion or archive",
        "backup expiry",
        "restore and re-deletion handling",
        "storage cost",
    ],
    "material": True,
    "field": "privacy.retention",
}


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cpc = _load("context_profile_check")
cps = _load("context_profile_score")
VALIDATOR = cpc.load_validator()


def _case(case_id):
    return cps.load_case(KNOWN / case_id)


def _checked(key, profile, brief):
    return cpc.check(profile, brief, key["brief_sha256"], VALIDATOR)


def _diagnostics(key, profile, brief):
    # Inspect only specific existing diagnostics, never overall semantic acceptance.
    return {(f["reason"], f["ref"]) for f in cps.score(key, profile, brief, VALIDATOR)["structural_anchor"]["failures"]}


@pytest.mark.parametrize("case_id", [K06, K07])
def test_corrected_keys_lint_and_references_pass_the_real_structural_checker(case_id):
    key, brief, sha = _case(case_id)  # actual key lint, including reference-field coverage
    assert cps.lint_key(key, brief, sha) == []
    checked = _checked(key, key["profile"], brief)
    assert checked["ok"], checked["errors"]
    assert _diagnostics(key, key["profile"], brief) == set()


def test_k06_keeps_established_past_evidence_baselines_and_every_old_fact_id():
    key, _brief, _sha = _case(K06)
    profile = key["profile"]
    assert key["maturity"]["accepted"] == [{
        "stage": "established",
        "quotes": ["We have run NextStop for six years", PAST_FLAT],
    }]
    assert profile["maturity"]["stage"] == "established"
    assert profile["maturity"]["evidence"][1] == {
        "value": "1.1 million monthly users, flat for two years",
        "source": {
            "kind": "quote",
            "quote": (
                "It has 1.1 million monthly users and about 180,000 daily users, "
                "and these numbers have been flat for two years."
            ),
        },
    }
    assert [f["id"] for f in key["facts"]] == [f"F{i}" for i in range(1, 29)]
    assert key["facts"][2] == {
        "id": "F3", "anchors": ["flat for two years"], "primary": "maturity.evidence",
    }
    assert cps.fact_sections(key["facts"][2]) == ["maturity.evidence"]
    assert [(m["value"], m["unit"]) for m in profile["workload"]["observed"][:2]] == [
        (1100000, "users per month"), (180000, "users per day"),
    ]


def test_k06_keys_the_actual_conditional_agency_estimate_without_dropping_coverage():
    key, brief, _sha = _case(K06)
    assert ASHFORD_QUOTE in brief
    # Exact fixture assertion, not a classifier of arbitrary forecast meaning.
    assert key["profile"]["workload"]["projected"] == [ASHFORD_PROJECTION]
    assert key["facts"][-1] == {
        "id": "F28",
        "anchors": ["would bring about 400,000 more monthly users"],
        "primary": "workload.projected",
        "value": 400000,
    }
    assert key["traps"][1] == {
        "id": "T2",
        "anchors": ["about 400,000 more monthly users"],
        "reason": "projected_as_observed",
        "forbidden_in": ["workload.observed", "maturity.evidence"],
    }


def test_k06_past_flat_is_not_credited_as_a_quoted_future_forecast():
    key, brief, _sha = _case(K06)
    profile = copy.deepcopy(key["profile"])
    profile["maturity"]["evidence"].pop(1)
    profile["workload"]["projected"].append({
        "what": "user numbers expected to stay as they are (flat for two years)",
        "value": "flat",
        "unit": "trend",
        "source": {"kind": "quote", "quote": PAST_FLAT},
    })
    assert _checked(key, profile, brief)["ok"]
    assert _diagnostics(key, profile, brief) == {("fact_misplaced", "F3")}


@pytest.mark.parametrize("section", ["workload.observed", "maturity.evidence"])
def test_k06_the_agency_estimate_cannot_be_observed_load_or_proven_demand(section):
    key, brief, _sha = _case(K06)
    profile = copy.deepcopy(key["profile"])
    if section == "workload.observed":
        profile["workload"]["observed"].append(copy.deepcopy(ASHFORD_PROJECTION))
    else:
        profile["maturity"]["evidence"].append({
            "value": "Ashford's conditional estimate of about 400,000 additional monthly users",
            "source": {"kind": "quote", "quote": ASHFORD_QUOTE},
        })
    assert _checked(key, profile, brief)["ok"]
    assert _diagnostics(key, profile, brief) == {("trap:projected_as_observed", "T2")}


def test_k06_omitting_the_conditional_projection_loses_the_new_fact_not_the_old_one():
    key, brief, _sha = _case(K06)
    profile = copy.deepcopy(key["profile"])
    profile["workload"]["projected"] = []
    assert _checked(key, profile, brief)["ok"]  # Ashford's existing named uncertainty remains
    assert _diagnostics(key, profile, brief) == {("fact_missed", "F28")}


def test_k07_retention_is_a_material_unanswered_decision_not_a_policy_or_legal_answer():
    key, _brief, _sha = _case(K07)
    profile = key["profile"]
    assert [f["id"] for f in key["facts"]] == [f"F{i}" for i in range(1, 19)]
    assert [u["id"] for u in key["unknowns"]] == [f"U{i}" for i in range(1, 8)]
    assert key["unknowns"][-1] == {
        "id": "U7", "field": "privacy.retention",
        "terms": [["retention", "retain", "kept", "keep", "delete", "deletion"],
                  ["customer", "personal", "booking"]],
    }
    field = next(f for f in key["fields_unknown"] if f["field"] == "privacy.retention")
    assert field == {"field": "privacy.retention", "open_anchors": []}
    question = next(u for u in profile["unknowns"] if u.get("field") == "privacy.retention")
    assert question == RETENTION_QUESTION  # fixed scoped assertion, not a general meaning check
    assert profile["privacy"]["retention"] == [] and profile["assumptions"] == []
    assert profile["constraints"][1]["source"]["quote"] == "Customers in the EU are covered by GDPR"
    for field in ("reliability.data_loss_tolerance", "reliability.recovery_time"):
        assert cpc.at(profile, field) == "unknown"
        assert next(u for u in profile["unknowns"] if u.get("field") == field)["material"] is True


def test_k07_dismissing_the_same_retention_question_is_the_specific_materiality_error():
    key, brief, _sha = _case(K07)
    profile = copy.deepcopy(key["profile"])
    next(u for u in profile["unknowns"] if u.get("field") == "privacy.retention")["material"] = False
    assert _checked(key, profile, brief)["ok"]
    assert _diagnostics(key, profile, brief) == {("unknown_not_material", "U7")}


def test_k07_omitting_retention_causes_only_its_named_silence_and_material_unknown_errors():
    key, brief, _sha = _case(K07)
    profile = copy.deepcopy(key["profile"])
    profile["unknowns"] = [u for u in profile["unknowns"] if u.get("field") != "privacy.retention"]
    checked = _checked(key, profile, brief)
    assert [(e["reason"], e["path"]) for e in checked["errors"]] == [
        ("unknown_field_unnamed", "$.privacy.retention"),
    ]
    assert _diagnostics(key, profile, brief) == {
        ("checker:unknown_field_unnamed", "$.privacy.retention"),
        ("unknown_not_flagged", "U7"),
    }


@pytest.mark.parametrize("source_kind,reason", [
    ("assumption", "guessed_unknown"), ("quote", "unsupported_fill"),
])
def test_k07_a_fabricated_retention_answer_does_not_replace_the_unknown(source_kind, reason):
    key, brief, _sha = _case(K07)
    profile = copy.deepcopy(key["profile"])
    if source_kind == "assumption":
        answer = {
            "value": "90 days",
            "source": {"kind": "assumption", "why": "A fabricated negative contrast, not a supplied policy."},
        }
    else:
        answer = {
            "value": "Customer booking data is retained indefinitely",
            "source": copy.deepcopy(profile["privacy"]["data_categories"][0]["source"]),
        }
    profile["privacy"]["retention"] = [answer]
    assert _checked(key, profile, brief)["ok"]  # no unrelated numeric or quote failure
    assert _diagnostics(key, profile, brief) == {(reason, "privacy.retention")}


def test_k07_material_retention_metadata_cannot_lose_its_required_unknown_silently():
    key, brief, sha = _case(K07)
    broken = copy.deepcopy(key)
    broken["unknowns"].pop()
    problems = cps.lint_key(broken, brief, sha)
    assert len(problems) == 1
    assert "privacy.retention" in problems[0] and "exactly one" in problems[0]
