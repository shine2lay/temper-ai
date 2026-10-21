"""H-CTX-6a fixed deterministic stage checks. No sealed/dev data or services.

The ten #133 profiles are byte copies, not reconstructions or mutated references.
This module never calls the scorer's grading functions. Empty findings are NOT support.
"""
import copy
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "configs/architecture/bin"
KNOWN = ROOT / "configs/architecture/fixtures/context_profile/known"
FIXTURES = Path(__file__).resolve().parent / "fixtures/context_profile_meaning_133"
SCRIPT = BIN / "context_profile_meaning.py"
SCHEMA = json.loads((ROOT / "configs/architecture/stages/context_profile/contract.v2.schema.json").read_text())
spec = importlib.util.spec_from_file_location("context_profile_meaning", SCRIPT)
cpm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cpm)

CLEAN13 = "2cd525f6f980886a9fba9a7ecf89a3376e40f7461b01260525538f898cf56023"
# SHA-256 values from #133 EXPECTED.json / REPORT.md, frozen before this checker existed.
PAIRS = (
    ("p01-comparator", "k13-performance-docks", CLEAN13,
     "d46b9c7d77d39298d91c34eb82c6ff06cf1b43985e66be7cc474e1ff4bfbefdd",
     ("/constraints/0/text",), "contradicted"),
    ("p02-unit", "k13-performance-docks", CLEAN13,
     "c380e08732f16976a65799c93372bae0ef59f02837b968e0aa44da7c5b295724",
     ("/performance/targets/0/unit",), "contradicted"),
    ("p03-loss", "k13-performance-docks", CLEAN13,
     "27ec0bc5f0398dc2b9ae0062572ee382f90331cade32acae2e9a483a7b8c6d7f",
     ("/reliability/data_loss_tolerance/value",), "needs_judgment"),
    ("p04-security", "k13-performance-docks", CLEAN13,
     "c7a0b68d8cc5f0eee5d131927fee6421de7c4174ffade40b164d20f64600a4cb",
     ("/security/requirements/1",), "needs_judgment"),
    ("p05-unknown", "k07-conflict-marketplace", "28855849988f97857bc2b66ddc9e38e3e13785910c5a8d577e2d51eff53c826c",
     "a7c55067e2f392b159d4d943160ce43aa15e42d83b7ed78c31b43fc143ad7330",
     ("/unknowns/4/question", "/unknowns/4/why_it_matters", "/unknowns/4/decisions_affected"), "needs_judgment"),
)


@lru_cache
def case(case_id):
    key, brief, _sha = cpm.cps.load_case(KNOWN / case_id)
    return key, brief


def candidate(pair, bad):
    name = f"{pair[0]}-{'bad' if bad else 'clean'}.json"
    blob = (FIXTURES / name).read_bytes()
    assert hashlib.sha256(blob).hexdigest() == pair[3 if bad else 2], name
    return json.loads(blob)


def run_profile(profile, case_id):
    key, brief = case(case_id)
    return cpm.check(profile, brief, key)


def by_path(result):
    return {r["path"]: r for r in result["claims"]}


def rules(a, b, path=""):
    return {f["rule"] for f in cpm.compare(a, b, path)}


@pytest.mark.parametrize("claim,quote,rule,path", [
    ("API p95 above 250 ms", "API p95 below 250 ms", "comparator", ""),
    ("at most 250 ms", "under 250 ms", "comparator", ""),
    ("250 seconds", "250 milliseconds", "unit_scale", ""),
    ("250 MB", "250 ms", "unit_scale", ""),
    ("1.5 million requests", "1.5 thousand requests", "unit_scale", ""),
    ("25%", "20%", "number", ""),
    ("251 ms", "250 ms", "number", ""),
    ("6 requests per minute", "7 requests per minute", "number", ""),
    ("between 100 and 300 ms", "between 100 and 200 ms", "range", ""),
    ("events must be retained", "events must not be retained", "polarity", ""),
    ("events may be retained", "events may not be retained", "polarity", ""),
    ("traffic is steady", "traffic was steady", "time", ""),
    ("traffic would be steady", "traffic will be steady", "time", ""),
    ("if the link fails, cache the record", "cache the record unless the link fails", "condition", ""),
    ("growing", "maturity: established", "label", "/maturity/stage"),
    ("high", "sensitivity: low", "label", "/privacy/sensitivity/level"),
    ("none", "system state: exists", "label", "/current_system/state"),
    ("cost", "criterion: reliability", "label", "/goals/0/criterion"),
    ("stack", "item kind: hosting", "label", "/current_system/items/0/kind"),
    ("120 requests", "projected: 120 requests", "section", "/workload/observed/0/value"),
    ("keep records", "goal: keep records", "section", "/constraints/0/text"),
])
def test_positive_rule(claim, quote, rule, path):
    found = cpm.compare(claim, quote, path)
    assert rule in {f["rule"] for f in found}
    assert all("claim" in f and "quote" in f for f in found)


def test_seconds_conversion_trap():
    # Removing ms->s conversion must turn this equivalent pair into a false contradiction.
    assert cpm.compare("250 ms", "0.25 s") == []


@pytest.mark.parametrize("claim,quote,path", [
    ("under 250 ms", "< 250 ms", ""),
    ("at most 250 ms", "no more than 250 ms", ""),
    ("at least 250 ms", "no less than 250 ms", ""),
    ("above 250 ms", "> 250 ms", ""),
    ("exactly 250 ms", "equal to 250 ms", ""),
    ("1.5k requests", "1,500 requests", ""),
    ("$80,000", "The board has capped this rebuild at $80,000.", ""),
    ("250 ms.", "0.25 s", ""),
    ("1 million requests", "1,000 thousand requests", ""),
    ("1 billion requests", "1,000 million requests", ""),
    ("1.5m requests", "1,500k requests", ""),
    ("1b requests", "1,000m requests", ""),
    ("100%", "100 percent", ""),
    ("60 s", "1 min", ""),
    ("60 min", "1 h", ""),
    ("1 KB", "1,000 B", ""),
    ("1 MB", "1,000 KB", ""),
    ("1 GB", "1,000 MB", ""),
    ("1 TB", "1,000 GB", ""),
    ("1 KiB", "1,024 B", ""),
    ("1 MiB", "1,024 KiB", ""),
    ("1 GiB", "1,024 MiB", ""),
    ("1 TiB", "1,024 GiB", ""),
    ("60 events/minute", "1 event per second", ""),
    ("3600 events/hour", "1 event/second", ""),
    ("86400 events/day", "1 event/second", ""),
    ("600 events/month", "600 events per month", ""),
    ("400 MB/s", "24 GB/min", ""),
    ("latency below 250 ms on the board", "the board has latency under 250 milliseconds", ""),
    ("events must never be lost", "events must not be lost", ""),
    ("the link must work", "work is required for the link", ""),
    ("traffic was steady", "steady was the traffic", ""),
    ("cache the record if the link fails", "if the link fails, cache the record", ""),
    ("cache the record if the link fails", "cache the record when the link fails", ""),
    ("low", "sensitivity: low", "/privacy/sensitivity/level"),
    ("120 requests", "observed: 120 requests", "/workload/observed/0/value"),
    ("keep records", "constraint: keep records", "/constraints/0/text"),
])
def test_equivalence_traps(claim, quote, path):
    assert cpm.compare(claim, quote, path) == []


@pytest.mark.parametrize("claim,quote", [
    ("250 ms", "250 ms or 500 ms"),
    ("250 ms", "about 200 ms"),
    ("250 ms", "not below 250 ms"),
    ("250 ms", "no faster than 200 ms"),
    ("100 events/month", "100 events/day"),
    ("250", "200"),
    ("250 widgets", "250 gadgets"),
    ("250 mbit", "250 MB"),
    ("250 MB/fortnight", "250 MB/hour"),
    ("p95 latency", "SOC2 compliance"),
    ("acknowledged events may be lost", "An event we have acknowledged must never be lost"),
    ("traffic may be high", "traffic will be high"),
    ("cache if offline or if busy", "cache unless offline"),
    ("the service is live and is fast", "the service was live and was fast"),
])
def test_ambiguity_defers(claim, quote):
    assert cpm.compare(claim, quote) == []


@pytest.mark.parametrize("pair", PAIRS, ids=lambda p: p[0])
@pytest.mark.parametrize("bad", (False, True), ids=("clean", "bad"))
def test_h_ctx_6a_pairs(pair, bad):
    result = run_profile(candidate(pair, bad), pair[1])
    claims = by_path(result)
    faults, expected = pair[4], pair[5]
    if bad:
        for path in faults:
            assert claims[path]["outcome"] == expected, (path, claims[path])
        # Ancestor group summaries may repeat evidence, but no sibling assertion may be faulted.
        permitted = {p for f in faults for p in (f, f.rsplit("/", 1)[0])}
        assert {p for p, r in claims.items() if r["outcome"] == "contradicted"} <= permitted
    else:
        assert all(r["outcome"] == "needs_judgment" for r in claims.values())
    assert len(claims) == len(result["inventory"]["claims"]) == result["summary"]["entries"]


def test_p01_comparator_bite():
    result = by_path(run_profile(candidate(PAIRS[0], True), PAIRS[0][1]))
    fault = result["/constraints/0/text"]
    assert fault["outcome"] == "contradicted"
    assert [f["rule"] for f in fault["findings"]] == ["comparator"]


@pytest.mark.parametrize("case_id", sorted(p.name for p in KNOWN.iterdir() if p.is_dir()))
def test_known_reference_has_no_contradictions(case_id):
    key, brief = case(case_id)
    result = cpm.check(key["profile"], brief, key)
    assert len([p for p in KNOWN.iterdir() if p.is_dir()]) == 14
    assert all(r["outcome"] == "needs_judgment" for r in result["claims"]), [r for r in result["claims"] if r["outcome"] != "needs_judgment"]


def test_never_supported():
    for pair in PAIRS:
        for bad in (False, True):
            result = run_profile(candidate(pair, bad), pair[1])
            assert {r["outcome"] for r in result["claims"]} <= {"contradicted", "needs_judgment"}
            assert all(r["outcome"] != "supported" for r in result["claims"])
            assert not ({"score", "score_pct", "accepted", "supported", "meets_bars"} & result.keys())


# Independent enumeration: walk raw JSON, never call cpm.inventory or cpm.pointer.
def expected_leaves(value, path=""):
    if isinstance(value, dict):
        result = set()
        for name, child in value.items():
            p = path + "/" + name.replace("~", "~0").replace("/", "~1")
            if name in ("contract", "brief_sha256", "id") or (path.endswith("/source") and name in ("kind", "quote")):
                continue
            result |= expected_leaves(child, p)
        return result
    if isinstance(value, list):
        result = {path} if not value or all(not isinstance(c, (dict, list)) for c in value) else set()
        return result | set().union(*(expected_leaves(c, f"{path}/{i}") for i, c in enumerate(value)))
    return {path}


def resolve(node):
    while "$ref" in node:
        node = SCHEMA["$defs"][node["$ref"].split("/")[-1]]
    return node


def schema_leaves(node, path=""):
    node = resolve(node)
    if "oneOf" in node:
        return set().union(*(schema_leaves(c, path) for c in node["oneOf"]))
    if node.get("type") == "object":
        return set().union(*(schema_leaves(c, path + "/" + k) for k, c in node["properties"].items()
                             if k not in ("contract", "brief_sha256", "id") and not (path.endswith("/source") and k in ("kind", "quote"))))
    if node.get("type") == "array":
        return schema_leaves(node["items"], path + "/*")
    return {path}


def sample(node, assumptions=False, unknowns=False, path=""):
    node = resolve(node)
    if "oneOf" in node:
        choices = node["oneOf"]
        choose = unknowns if resolve(choices[-1]).get("const") == "unknown" else assumptions
        return sample(choices[int(choose)], assumptions, unknowns, path)
    if "const" in node:
        return node["const"]
    if "enum" in node:
        return node["enum"][0]
    if node.get("type") == "object":
        return {k: sample(c, assumptions, unknowns, path + "/" + k) for k, c in node["properties"].items()}
    if node.get("type") == "array":
        return [sample(node["items"], assumptions, unknowns, path + "/*")]
    if node.get("type") == "boolean":
        return True
    if node.get("type") in ("number", "integer") or isinstance(node.get("type"), list):
        return 7
    if node.get("pattern") == "^[0-9a-f]{64}$":
        return "0" * 64
    if path.endswith("/id"):
        return "C1" if "constraints" in path else "G1"
    return "xxxxxxxx"


def assert_inventory(profile):
    inventory = cpm.inventory(profile)
    actual = {c["path"] for c in inventory if c["kind"] != "group"}
    assert actual == expected_leaves(profile)
    assert len(inventory) == len({c["path"] for c in inventory})
    return actual


def test_every_schema_claim_location_is_enumerated():
    observed = set()
    for assumptions in (False, True):
        for unknowns in (False, True):
            profile = sample(SCHEMA, assumptions, unknowns)
            assert cpm.cpc.load_validator().errors(profile) == []
            leaves = assert_inventory(profile)
            observed |= {re.sub(r"/\d+(?=/|$)", "/*", p) for p in leaves if not p.endswith("/decisions_affected")}
    assert observed == schema_leaves(SCHEMA)


def test_inventory_coverage_all_24_profiles():
    for pair in PAIRS:
        for bad in (False, True):
            assert_inventory(candidate(pair, bad))
    for directory in sorted(p for p in KNOWN.iterdir() if p.is_dir()):
        key, brief = case(directory.name)
        assert_inventory(key["profile"])
        result = cpm.check(key["profile"], brief, key)
        assert {c["path"] for c in result["inventory"]["claims"]} == set(by_path(result))
        expected = {f"/{category}/{i}" for category in ("facts", "constraints", "goals", "unknowns", "fields_unknown")
                    for i, entry in enumerate(key.get(category, []))
                    if entry.get("material") is not False and not entry.get("not_material_reason")}
        assert {o["path"] for o in result["inventory"]["obligations"]} == expected


def test_missing_duplicate_unmapped_obligations():
    profile = candidate(PAIRS[0], False)
    profile["constraints"] = profile["constraints"][1:]
    profile["external_systems"].append(copy.deepcopy(profile["external_systems"][0]))
    result = run_profile(profile, PAIRS[0][1])
    inv = result["inventory"]
    assert "/constraints/0" in inv["missing"]
    assert inv["duplicate_mappings"] and inv["duplicate_claims"]
    assert "/privacy/sensitivity/source/why" in inv["unmapped"]
    assert len(inv["obligations"]) == len(cpm.obligations(case(PAIRS[0][1])[0]))
    for claim in inv["claims"]:
        expected = [o["path"] for o in inv["obligations"] if claim["group"] in o["claim_groups"]]
        assert claim["obligations"] == expected


def test_unknown_mapping_checks_words_not_only_field():
    pair = PAIRS[4]
    clean = run_profile(candidate(pair, False), pair[1])
    bad = run_profile(candidate(pair, True), pair[1])
    clean_u = next(o for o in clean["inventory"]["obligations"] if o["id"] == "U5")
    bad_u = next(o for o in bad["inventory"]["obligations"] if o["id"] == "U5")
    assert "/unknowns/4" in clean_u["claim_groups"]
    assert bad_u["claim_groups"] == []
    assert bad_u["path"] in bad["inventory"]["missing"]


def test_ambiguity_at_profile_level_defers():
    profile = candidate(PAIRS[0], False)
    profile["performance"]["targets"][0]["source"]["quote"] = "A quote that is not in the brief"
    result = by_path(run_profile(profile, PAIRS[0][1]))
    assert result["/performance/targets/0/unit"]["outcome"] == "needs_judgment"
    assert result["/privacy/sensitivity/level"]["outcome"] == "needs_judgment"
    assert result["/security/threats"]["outcome"] == "needs_judgment"


def cli(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True, check=False)


@pytest.mark.parametrize("bad", (False, True))
def test_completed_cli_exits_one(bad):
    name = f"p01-comparator-{'bad' if bad else 'clean'}.json"
    run = cli("--case", KNOWN / PAIRS[0][1], FIXTURES / name)
    assert run.returncode == 1, run.stderr
    result = json.loads(run.stdout)
    assert result["format"] == "context_profile_meaning/v0-layers12"
    assert by_path(result)["/constraints/0/text"]["outcome"] == ("contradicted" if bad else "needs_judgment")


@pytest.mark.parametrize("payload", ["{bad", '{"contract": "x", "contract": "y"}', '{"x": NaN}', '{}', '[]', '"unknown"'])
def test_cannot_run_exits_two(tmp_path, payload):
    path = tmp_path / "invalid.json"
    path.write_text(payload)
    run = cli("--case", KNOWN / PAIRS[0][1], path)
    assert run.returncode == 2
    assert "error" in json.loads(run.stdout)


def test_no_zero_cli_route(tmp_path):
    assert cli("--help").returncode == 2
    assert cli().returncode == 2
    assert cli("--case", KNOWN / PAIRS[0][1], tmp_path / "absent.json").returncode == 2
    profile = candidate(PAIRS[0], False)
    profile["brief_sha256"] = "0" * 64
    path = tmp_path / "wrong-binding.json"
    path.write_text(json.dumps(profile))
    assert cli("--case", KNOWN / PAIRS[0][1], path).returncode == 2
    assert cli("--case", tmp_path / "absent-case", FIXTURES / "p01-comparator-clean.json").returncode == 2


def test_malformed_duplicate_key_exits_two(tmp_path):
    (tmp_path / "key.json").write_text('{"key": "x", "key": "y"}')
    assert cli("--case", tmp_path, FIXTURES / "p01-comparator-clean.json").returncode == 2
