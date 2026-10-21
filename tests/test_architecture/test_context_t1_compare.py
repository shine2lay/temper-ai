"""D3 standalone stage tests on invented fixtures, no judge/model/payload access."""
import copy
import json
import os
import runpy
import stat
from collections import Counter
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

F = runpy.run_path(str(Path(__file__).parent / "fixtures/context_t1/compare_aggregate/synthetic.py"))
d3, Corpus, write = F["d3"], F["Corpus"], F["write"]


@pytest.fixture
def corpus(tmp_path):
    return Corpus(tmp_path / "synthetic")


def test_complete_separate_toy_key_and_freeze_pass(corpus):
    result = corpus.compare()
    assert result["verdict"] == "PASS"
    assert result["class_matches"] == 37
    assert result["applicable_bad_family_matches"] == 19
    assert result["nonbad_null_families"] == 18
    assert result["false_support"] == 0
    assert result["known_bad_or_uncertain_cases"] == 28
    assert {name: item["matches"] for name, item in result["classes"].items()} == {
        "supported": 9, "contradicted": 10, "unsupported": 9, "uncertain": 9}
    assert {name: item["matches"] for name, item in result["families"].items()} == dict(zip(
        [f"F{i:02d}" for i in range(1, 13)], [1, 1, 2, 1, 2, 2, 2, 2, 1, 2, 1, 2], strict=True))
    assert result["key_sha256"] == corpus.key_pin
    assert result["freeze_sha256"] == corpus.freeze_pin
    assert stat.S_IMODE((corpus.root / "A1.comparison.json").stat().st_mode) == 0o600
    assert (corpus.root / "A1.comparison.json").stat().st_nlink == 1


def test_alternative_valid_literal_span_and_rationale_still_match(corpus):
    document = copy.deepcopy(corpus.key)
    for row in document["decisions"]:
        row["source_span"] = "none" if row["label"] == "unsupported" else 'Alternative exact quote: "blue"'
        assert row["source_span"] == "none" or row["source_span"] in F["BRIEF"]
        row["rationale"] = "An independently reviewed different rationale: café α."
    corpus.answer("A1", document)
    assert corpus.compare()["verdict"] == "PASS"


def test_reordered_decisions_and_1500_unicode_rationale_pass(corpus):
    document = copy.deepcopy(corpus.key)
    document["decisions"].reverse()
    document["decisions"][0]["rationale"] = "α" * 1500
    corpus.answer("A1", document)
    assert corpus.compare()["verdict"] == "PASS"


@pytest.mark.parametrize("label,replacement", [("supported", "uncertain"), ("contradicted", "unsupported"),
                                               ("unsupported", "contradicted"), ("uncertain", "supported")])
def test_one_error_in_each_class_fails(corpus, label, replacement):
    document = copy.deepcopy(corpus.key)
    row = next(row for row in document["decisions"] if row["label"] == label)
    row["label"] = replacement
    if replacement not in ("contradicted", "unsupported"):
        row["family"] = None
    corpus.answer("A1", document)
    result = corpus.compare()
    assert result["verdict"] == "FAIL"
    assert result["class_matches"] == 36
    assert result["classes"][label]["matches"] == result["classes"][label]["total"] - 1


@pytest.mark.parametrize("family", [f"F{i:02d}" for i in range(1, 13)])
def test_each_bad_family_wrong_fails(corpus, family):
    document = copy.deepcopy(corpus.key)
    row = next(row for row in document["decisions"] if row["family"] == family)
    row["family"] = "F02" if family == "F01" else "F01"
    corpus.answer("A1", document)
    result = corpus.compare()
    assert result["verdict"] == "FAIL"
    assert result["class_matches"] == 37
    assert result["applicable_bad_family_matches"] == 18
    assert result["families"][family]["matches"] == result["families"][family]["total"] - 1


@pytest.mark.parametrize("label", ["contradicted", "unsupported", "uncertain"])
def test_false_support_each_bad_or_uncertain_class(corpus, label):
    document = copy.deepcopy(corpus.key)
    row = next(row for row in document["decisions"] if row["label"] == label)
    row.update(label="supported", family=None, source_span="the toy lamp is blue")
    corpus.answer("A1", document)
    result = corpus.compare()
    assert result["verdict"] == "FAIL" and result["false_support"] == 1


def test_swapped_ids_refused_not_positionally_compared(corpus):
    document = copy.deepcopy(corpus.key)
    left, right = document["decisions"][0], document["decisions"][9]
    left["id"], right["id"] = right["id"], left["id"]
    corpus.answer("A1", document)
    with pytest.raises(d3.Refusal, match="path_binding"):
        corpus.compare()
    assert not (corpus.root / "A1.comparison.json").exists()


def test_same_totals_permuted_answers_are_not_success(corpus):
    document = copy.deepcopy(corpus.key)
    left, right = document["decisions"][0], document["decisions"][9]
    for name in ("label", "family", "source_span", "rationale"):
        left[name], right[name] = right[name], left[name]
    assert Counter(row["label"] for row in document["decisions"]) == Counter(row["label"] for row in corpus.key["decisions"])
    assert Counter(row["family"] for row in document["decisions"]) == Counter(row["family"] for row in corpus.key["decisions"])
    corpus.answer("A1", document)
    result = corpus.compare()
    assert result["verdict"] == "FAIL" and result["class_matches"] == 35


@pytest.mark.parametrize("which", ["key", "freeze", "pin"])
def test_unbound_key_or_freeze_refused(corpus, which):
    if which == "key":
        changed = copy.deepcopy(corpus.key)
        changed["decisions"][0]["rationale"] = "Still valid key shape, now unbound bytes."
        write(corpus.root, "key/EXPECTED.json", changed)
    elif which == "freeze":
        write(corpus.root, "key/EXPECTED-FREEZE.json", {"schema": "t0-expected-freeze/v1", "sha256": {}})
    else:
        corpus.freeze_pin = "0" * 64
    with pytest.raises(d3.Refusal, match="binding"):
        corpus.compare()
    assert not (corpus.root / "A1.comparison.json").exists()


@pytest.mark.parametrize("field,value", [("verdict", "REJECT"), ("slot", "B1"), ("raw_sha256", "0" * 64),
                                         ("raw_bytes", 1), ("raw_bytes", True), ("reject_reasons", ["invalid"]),
                                         ("packet_sha256", None), ("decision_ids", [])])
def test_validation_not_pass_or_not_bound_refused(corpus, field, value):
    validation = json.loads((corpus.root / "A1.validation.json").read_text())
    validation[field] = value
    write(corpus.root, "A1.validation.json", validation)
    with pytest.raises(d3.Refusal):
        corpus.compare()
    assert not (corpus.root / "A1.comparison.json").exists()


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "path", "nonbad_family", "bad_null", "type", "extra_field"])
def test_raw_identity_and_shape_refused_even_if_d2_claims_pass(corpus, mutation):
    document = copy.deepcopy(corpus.key)
    if mutation == "missing":
        document["decisions"].pop()
    elif mutation == "extra":
        document["decisions"].append({**document["decisions"][0], "id": "invented-extra"})
    elif mutation == "duplicate":
        document["decisions"][0]["id"] = document["decisions"][1]["id"]
    elif mutation == "path":
        document["decisions"][0]["path"] = "/invented/wrong"
    elif mutation == "nonbad_family":
        document["decisions"][0]["family"] = "F01"
    elif mutation == "bad_null":
        document["decisions"][9]["family"] = None
    elif mutation == "type":
        document["decisions"][0]["label"] = []
    else:
        document["decisions"][0]["extra"] = "not admitted"
    corpus.answer("A1", document)
    with pytest.raises(d3.Refusal):
        corpus.compare()


@pytest.mark.parametrize("raw", [b"\xef\xbb\xbf{}", b"\xff", b"{} trailing", b"```json\n{}\n```", b'{"x":1,"x":2}',
                                b'{"x":{"x":1,"x":2}}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}',
                                b'{"x":5.0000000000000001}', b'{"x":1e-999}', b'{"x":"\\ud800"}'])
def test_strict_json_bytes_refused(corpus, raw):
    raw_pin = write(corpus.root, "A1.raw.json", raw)
    validation = json.loads((corpus.root / "A1.validation.json").read_text())
    validation.update(raw_sha256=raw_pin, raw_bytes=len(raw))
    write(corpus.root, "A1.validation.json", validation)
    with pytest.raises(d3.Refusal):
        corpus.compare()


@pytest.mark.parametrize("unsafe", ["symlink", "ancestor_symlink", "hardlink", "fifo", "mode", "directory_mode", "oversize"])
def test_private_file_envelope_refused(corpus, unsafe):
    raw = corpus.root / "A1.raw.json"
    if unsafe == "symlink":
        raw.unlink()
        raw.symlink_to(corpus.root / "B1.raw.json")
    elif unsafe == "ancestor_symlink":
        (corpus.root / "alias").symlink_to(corpus.root / "key", target_is_directory=True)
    elif unsafe == "hardlink":
        os.link(raw, corpus.root / "extra-link")
    elif unsafe == "fifo":
        raw.unlink()
        os.mkfifo(raw, 0o600)
    elif unsafe == "mode":
        raw.chmod(0o644)
    elif unsafe == "directory_mode":
        (corpus.root / "key").chmod(0o755)
    else:
        write(corpus.root, "A1.raw.json", b"x" * 2_000_001)
    with pytest.raises((d3.Refusal, OSError)):
        d3.compare(corpus.root, "A1", corpus.freeze_pin,
                   key="alias/EXPECTED.json" if unsafe == "ancestor_symlink" else "key/EXPECTED.json")
    assert not (corpus.root / "A1.comparison.json").exists()


@pytest.mark.parametrize("path", ["../key/EXPECTED.json", "/etc/passwd", "key//EXPECTED.json", "key/./EXPECTED.json", "key\\EXPECTED.json"])
def test_traversal_or_ambiguous_path_refused(corpus, path):
    with pytest.raises(d3.Refusal, match="path"):
        d3.compare(corpus.root, "A1", corpus.freeze_pin, key=path)


def test_output_exclusive_first_result_preserved(corpus):
    corpus.compare()
    before = (corpus.root / "A1.comparison.json").read_bytes()
    with pytest.raises(FileExistsError):
        corpus.compare()
    assert (corpus.root / "A1.comparison.json").read_bytes() == before


def test_output_mode_is_exact_even_with_restrictive_umask(corpus):
    previous = os.umask(0o777)
    try:
        corpus.compare()
    finally:
        os.umask(previous)
    assert stat.S_IMODE((corpus.root / "A1.comparison.json").stat().st_mode) == 0o600


def test_output_symlink_not_followed(corpus):
    target = corpus.root / "B1.raw.json"
    before = target.read_bytes()
    (corpus.root / "A1.comparison.json").symlink_to(target)
    with pytest.raises(OSError):
        corpus.compare()
    assert target.read_bytes() == before


def test_descriptor_cleanup_on_repeated_refusal(corpus):
    before = F["fds"]()
    for _ in range(40):
        with pytest.raises(d3.Refusal):
            d3.compare(corpus.root, "A1", "0" * 64)
    assert F["fds"]() == before


def test_comparison_schema_and_instance(corpus):
    schema = json.loads((F["SCHEMAS"] / "comparison.v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(corpus.compare())
    assert set(schema["required"]) == d3.COMPARISON_FIELDS


def test_cli_pass_and_refusal_expose_only_status(corpus, capsys):
    argv = ["--root", str(corpus.root), "--slot", "A1", "--freeze-sha256", corpus.freeze_pin]
    assert d3.main(argv) == 0
    assert json.loads(capsys.readouterr().out) == {"slot": "A1", "verdict": "PASS"}
    assert d3.main(argv) == 2
    assert json.loads(capsys.readouterr().out) == {"slot": "A1", "verdict": "REFUSED"}
