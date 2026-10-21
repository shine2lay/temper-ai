"""D2 standalone synthetic strict-output coverage; no model/key/real controls.

H-T1-D12-1: every frozen strict_output.reject condition is refused, not repaired.
The stage fixture assembles known synthetic projection metadata, never runs D1
or inspects a model payload. D2 format PASS is not semantic correctness/admission.
Sentinel cases implement ERRATUM-1, including literal-source versus sentinel use.
"""
import copy
import importlib
import json
import os
import stat
import sys
from pathlib import Path

import jsonschema
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "configs/architecture/bin"))
d1 = importlib.import_module("context_t1_project")
d2 = importlib.import_module("context_t1_validate")
FIXTURES = Path(__file__).parent / "fixtures/context_t1/project_validate"
SCHEMA = REPO / "configs/architecture/stages/context_profile/t1/validation.v1.schema.json"


def put(path, raw):
    path.write_bytes(raw)
    path.chmod(0o600)


@pytest.fixture
def stage(tmp_path):
    source, output = tmp_path / "input", tmp_path / "output"
    source.mkdir(mode=0o700)
    output.mkdir(mode=0o700)
    packet_raw = (FIXTURES / "packet.json").read_bytes()
    packet = json.loads(packet_raw)
    document = json.loads((FIXTURES / "good-answer.json").read_bytes())
    inputs = {name: {"sha256": d1.digest((FIXTURES / file).read_bytes()),
                     "bytes": len((FIXTURES / file).read_bytes())} for name, file in
              (("packet", "packet.json"), ("label_rules", "rules.txt"), ("format", "format.txt"))}
    projection = {"schema": "context-t1-projection/v1", "inputs": inputs,
                  "inventory": [{"id": row["id"], "path": row["path"]} for row in packet["controls"]],
                  "prompt_sha256": "1" * 64,
                  "prompt_bytes": d1.FRAMING_BYTES + sum(binding["bytes"] for binding in inputs.values())}
    put(source / "packet.json", packet_raw)
    put(source / "projection.json", d1.json_bytes(projection))
    put(source / "answer.json", d1.json_bytes(document))
    return {"source": source, "output": output, "document": document,
            "packet": packet, "projection": projection, "packet_raw": packet_raw}


def call(stage, **changes):
    options = dict(input_root=stage["source"], raw="answer.json", packet="packet.json",
                   projection="projection.json", slot="A1", output_root=stage["output"])
    options.update(changes)
    result = d2.validate_slot(**options)
    stored = (stage["output"] / f'{options["slot"]}.validation.json').read_bytes()
    assert json.loads(stored) == result
    schema = json.loads(SCHEMA.read_bytes())
    assert jsonschema.Draft202012Validator(schema).is_valid(result)
    path = stage["output"] / f'{options["slot"]}.validation.json'
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.stat().st_nlink == 1
    return result


def answer(stage, document=None, raw=None):
    put(stage["source"] / "answer.json", raw if raw is not None else d1.json_bytes(
        stage["document"] if document is None else document))


def reject(stage, code, **changes):
    result = call(stage, **changes)
    assert result["verdict"] == "REJECT"
    assert result["reject_reasons"] == [code]
    assert "decision_ids" not in result
    return result


def update_packet_binding(stage):
    raw = d1.json_bytes(stage["packet"])
    projection = stage["projection"]
    delta = len(raw) - projection["inputs"]["packet"]["bytes"]
    projection["inputs"]["packet"] = {"sha256": d1.digest(raw), "bytes": len(raw)}
    projection["prompt_bytes"] += delta
    projection["inventory"] = [{"id": row["id"], "path": row["path"]} for row in stage["packet"]["controls"]]
    put(stage["source"] / "packet.json", raw)
    put(stage["source"] / "projection.json", d1.json_bytes(projection))


def test_four_classes_null_nonbad_families_and_exact_evidence_pass(stage):
    result = call(stage)
    assert result["verdict"] == "PASS"
    assert result["decision_ids"] == [row["id"] for row in stage["packet"]["controls"]]
    assert result["reject_reasons"] == []
    assert result["raw_sha256"] == d1.digest((stage["source"] / "answer.json").read_bytes())
    assert result["raw_bytes"] == (stage["source"] / "answer.json").stat().st_size
    assert result["packet_sha256"] == d1.digest(stage["packet_raw"])
    assert {row["label"] for row in stage["document"]["decisions"]} == set(d2.LABELS)
    assert all(row["family"] is None for row in stage["document"]["decisions"]
               if row["label"] in ("supported", "uncertain"))


@pytest.mark.parametrize("label", ["contradicted", "unsupported"])
@pytest.mark.parametrize("family", [f"F{i:02d}" for i in range(1, 13)])
def test_all_twelve_valid_families_pass(stage, label, family):
    stage["document"]["decisions"][0].update(label=label, family=family)
    answer(stage)
    assert call(stage)["verdict"] == "PASS"


def test_alternative_exact_span_and_answer_order_pass(stage):
    stage["document"]["decisions"][0]["source_span"] = "😀 opens locally."
    stage["document"]["decisions"].reverse()
    answer(stage)
    result = call(stage)
    assert result["verdict"] == "PASS"
    assert result["decision_ids"] == [row["id"] for row in stage["packet"]["controls"]]


@pytest.mark.parametrize("span", ["Á", "Keep  two spaces.", "“café”", "😀"] ,
                         ids=["decomposed_unicode", "double_space", "curly_quotes", "astral_unicode"])
def test_exact_unicode_quotes_whitespace_span_pass(stage, span):
    stage["document"]["decisions"][0]["source_span"] = span
    answer(stage)
    assert call(stage)["verdict"] == "PASS"


@pytest.mark.parametrize("length", [1, 1500])
def test_rationale_unicode_character_boundary_pass(stage, length):
    stage["document"]["decisions"][0]["rationale"] = "😀" * length
    answer(stage)
    assert call(stage)["verdict"] == "PASS"


def test_1501_character_rationale_refused(stage):
    stage["document"]["decisions"][0]["rationale"] = "😀" * 1501
    answer(stage)
    reject(stage, "rationale_too_long")


@pytest.mark.parametrize("rationale", ["", " ", "\n\t", "\u2000"], ids=["empty", "space", "ascii_space", "unicode_space"])
def test_empty_rationale_refused(stage, rationale):
    stage["document"]["decisions"][0]["rationale"] = rationale
    answer(stage)
    reject(stage, "empty_rationale")


def test_unsupported_exact_none_sentinel_pass(stage):
    assert stage["document"]["decisions"][2]["source_span"] == "none"
    assert call(stage)["verdict"] == "PASS"


@pytest.mark.parametrize("label", ["supported", "contradicted", "uncertain"])
def test_none_on_nonunsupported_refused_even_when_in_brief(stage, label):
    stage["packet"]["controls"][0]["brief"] += " The word none is literally here."
    update_packet_binding(stage)
    stage["document"]["decisions"][0].update(
        source_span="none", label=label, family="F01" if label == "contradicted" else None)
    answer(stage)
    reject(stage, "sentinel_label")


@pytest.mark.parametrize("span,code", [("<none>", "nonliteral_span"), ("None", "nonliteral_span"),
                                       ("NONE", "nonliteral_span"), (" none", "nonliteral_span"),
                                       ("none ", "nonliteral_span"), ("", "empty_span"),
                                       (None, "field_type")],
                         ids=["brackets", "title_case", "upper_case", "leading_space", "trailing_space", "empty", "null"])
def test_no_alternate_unsupported_sentinel(stage, span, code):
    stage["document"]["decisions"][2]["source_span"] = span
    answer(stage)
    reject(stage, code)


def test_sentinel_variant_is_only_ordinary_literal_source_text(stage):
    # ERRATUM-1 item 2: a non-sentinel spelling may still be an exact source quote.
    stage["packet"]["controls"][2]["brief"] += " The literal invented token is <none>."
    update_packet_binding(stage)
    stage["document"]["decisions"][2]["source_span"] = "<none>"
    answer(stage)
    assert call(stage)["verdict"] == "PASS"


def test_two_fragment_span_refused(stage):
    bad = json.loads((FIXTURES / "bad-answer-fragments.json").read_bytes())
    stage["document"]["decisions"][0]["source_span"] = bad["decisions"][0]["source_span"]
    answer(stage)
    reject(stage, "nonliteral_span")


@pytest.mark.parametrize("kind", ["other_case", "normalized_unicode", "normalized_space", "normalized_quotes"])
def test_nonliteral_or_other_case_span_refused(stage, kind):
    spans = {"other_case": "Lúcia mentions only a green door.", "normalized_unicode": "Á",
             "normalized_space": "Keep two spaces.", "normalized_quotes": '"café"'}
    stage["document"]["decisions"][0]["source_span"] = spans[kind]
    answer(stage)
    reject(stage, "nonliteral_span")


@pytest.mark.parametrize("kind,code", [("missing", "missing_id"), ("empty", "missing_id"),
                                       ("duplicate", "duplicate_id"), ("extra", "extra_id"),
                                       ("blank", "invalid_id")])
def test_missing_duplicate_extra_ids_refused(stage, kind, code):
    rows = stage["document"]["decisions"]
    if kind == "missing":
        rows.pop()
    elif kind == "empty":
        rows.clear()
    elif kind == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif kind == "extra":
        rows[0]["id"] = "unknown-invented-id"
    else:
        rows[0]["id"] = " "
    answer(stage)
    reject(stage, code)


@pytest.mark.parametrize("span", [" ", "\t\n", "\u2000"], ids=["space", "ascii_space", "unicode_space"])
def test_whitespace_only_span_refused(stage, span):
    stage["document"]["decisions"][0]["source_span"] = span
    answer(stage)
    reject(stage, "empty_span")


def test_wrong_path_refused(stage):
    stage["document"]["decisions"][0]["path"] = "/constraints/0"
    answer(stage)
    reject(stage, "target_path")


@pytest.mark.parametrize("label", ["SUPPORTED", "supported ", "unknown", "", "bad"])
def test_invalid_class_refused(stage, label):
    stage["document"]["decisions"][0]["label"] = label
    answer(stage)
    reject(stage, "label")


@pytest.mark.parametrize("family", [None, "F00", "F13", "F1", "F001", "f01", " F01", "F01 ", 1, False, []])
def test_invalid_bad_family_or_null_refused(stage, family):
    stage["document"]["decisions"][1]["family"] = family
    answer(stage)
    reject(stage, "family")


@pytest.mark.parametrize("label", ["supported", "uncertain"])
@pytest.mark.parametrize("family", ["F01", "null", 0, False, []])
def test_nonbad_family_must_be_json_null(stage, label, family):
    stage["document"]["decisions"][0].update(label=label, family=family)
    answer(stage)
    reject(stage, "nonbad_family")


@pytest.mark.parametrize("kind", ["top_extra", "top_missing", "row_extra", "row_missing"])
def test_extra_missing_fields_refused(stage, kind):
    doc = stage["document"]
    if kind == "top_extra":
        doc["unplanned"] = False
    elif kind == "top_missing":
        del doc["schema"]
    elif kind == "row_extra":
        doc["decisions"][0]["unplanned"] = False
    else:
        del doc["decisions"][0]["rationale"]
    answer(stage)
    reject(stage, "field_extra" if kind.endswith("extra") else "field_missing")


@pytest.mark.parametrize("key", ["id", "path", "label", "source_span", "rationale"])
@pytest.mark.parametrize("value", [None, 1, False, [], {}])
def test_no_field_type_coercion(stage, key, value):
    stage["document"]["decisions"][0][key] = value
    answer(stage)
    reject(stage, "field_type")


@pytest.mark.parametrize("kind", ["root_list", "row_list", "decisions_object", "schema_number"])
def test_wrong_container_type_refused(stage, kind):
    doc = stage["document"]
    if kind == "root_list":
        doc = []
    elif kind == "row_list":
        doc["decisions"][0] = []
    elif kind == "decisions_object":
        doc["decisions"] = {}
    else:
        doc["schema"] = 2
    answer(stage, document=doc)
    reject(stage, "field_type")


def test_wrong_schema_refused(stage):
    stage["document"]["schema"] = "candidate-decisions/v1"
    answer(stage)
    reject(stage, "schema")


def test_duplicate_key_at_depth_refused(stage):
    # Complete otherwise-valid answer, so disabling the key guard actually passes it.
    raw = d1.json_bytes(stage["document"]).replace(b'"rationale":', b'"rationale":"duplicate","rationale":', 1)
    answer(stage, raw=raw)
    reject(stage, "duplicate_json_key")


@pytest.mark.parametrize("kind", ["root", "nested_extra", "fixture"])
def test_duplicate_key_at_other_depths_refused(stage, kind):
    if kind == "root":
        raw = d1.json_bytes(stage["document"]).replace(b'"schema":', b'"schema":"duplicate","schema":', 1)
    elif kind == "nested_extra":
        raw = b'{"deep":{"deeper":{"x":1,"x":2}}}'
    else:
        raw = (FIXTURES / "bad-answer-duplicate.json").read_bytes()
    answer(stage, raw=raw)
    reject(stage, "duplicate_json_key")


@pytest.mark.parametrize("kind,code", [("utf8", "invalid_utf8"), ("bom", "bom"), ("fence", "code_fence"),
                                       ("prose", "prose"), ("trailing", "trailing_data"),
                                       ("malformed", "malformed_json"), ("empty", "malformed_json"),
                                       ("surrogate", "invalid_unicode")])
def test_strict_encoding_json_and_wrapper_refusals(stage, kind, code):
    good = d1.json_bytes(stage["document"])
    cases = {"utf8": b"\xff", "bom": b"\xef\xbb\xbf" + good,
             "fence": (FIXTURES / "bad-answer-fence.txt").read_bytes(),
             "prose": b"Here is the answer:\n" + good, "trailing": good + b"{}",
             "malformed": b'{"schema":', "empty": b"", "surrogate": b'{"x":"\\ud800"}'}
    answer(stage, raw=cases[kind])
    result = reject(stage, code)
    assert result["raw_sha256"] == d1.digest(cases[kind])
    assert result["raw_bytes"] == len(cases[kind])


@pytest.mark.parametrize("literal,code", [(b"NaN", "nan"), (b"Infinity", "infinity"),
                                          (b"-Infinity", "infinity"), (b"1e9999", "overflow_nonfinite")],
                         ids=["nan", "positive_infinity", "negative_infinity", "float_overflow"])
def test_nonfinite_json_refused(stage, literal, code):
    raw = d1.json_bytes(stage["document"]).replace(b'"family": null', b'"family": ' + literal, 1)
    answer(stage, raw=raw)
    reject(stage, code)


def test_structured_output_field_not_trusted_or_extracted(stage):
    answer(stage, document={"structured_output": stage["document"]})
    reject(stage, "field_extra")


@pytest.mark.parametrize("kind,code", [("symlink", "symlink"), ("hardlink", "hardlink"),
                                       ("fifo", "file_type"), ("directory", "file_type"),
                                       ("mode", "file_mode"), ("oversize", "size")])
def test_unsafe_raw_file_envelope_refused_without_hashing(stage, tmp_path, kind, code):
    target = stage["source"] / "answer.json"
    if kind == "symlink":
        other = tmp_path / "target.json"
        put(other, d1.json_bytes(stage["document"]))
        target.unlink()
        target.symlink_to(other)
    elif kind == "hardlink":
        os.link(target, tmp_path / "second-link.json")
    elif kind == "fifo":
        target.unlink()
        os.mkfifo(target, 0o600)
    elif kind == "directory":
        target.unlink()
        target.mkdir(mode=0o700)
    elif kind == "mode":
        target.chmod(0o644)
    else:
        put(target, b"x" * (d1.MAX_BYTES + 1))
    result = reject(stage, code)
    assert result["raw_sha256"] is None
    assert result["raw_bytes"] is None


def test_exact_raw_file_byte_limit_pass(stage):
    raw = d1.json_bytes(stage["document"])
    raw += b" " * (d1.MAX_BYTES - len(raw))
    answer(stage, raw=raw)
    result = call(stage)
    assert result["verdict"] == "PASS"
    assert result["raw_bytes"] == d1.MAX_BYTES


@pytest.mark.parametrize("path", ["../answer.json", "/answer.json", "a/../answer.json", "a//answer.json",
                                  "./answer.json", "a\\answer.json", "answer.json\x00"])
def test_raw_traversal_or_absolute_path_refused(stage, path):
    reject(stage, "path", raw=path)


def test_input_root_directory_symlink_refused(stage, tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(stage["source"], target_is_directory=True)
    reject(stage, "symlink", input_root=alias)


def test_nonprivate_input_root_refused(stage):
    stage["source"].chmod(0o750)
    reject(stage, "directory_mode")


def test_nested_raw_directory_symlink_refused(stage, tmp_path):
    other = tmp_path / "external"
    other.mkdir(mode=0o700)
    put(other / "answer.json", d1.json_bytes(stage["document"]))
    (stage["source"] / "nested").symlink_to(other, target_is_directory=True)
    reject(stage, "symlink", raw="nested/answer.json")


def test_file_changed_during_read_refused(stage, monkeypatch):
    read = d1.os.read
    changed = False

    def changing_read(fd, amount):
        nonlocal changed
        value = read(fd, amount)
        if value and not changed:
            changed = True
            with (stage["source"] / "answer.json").open("ab") as stream:
                stream.write(b" ")
        return value

    monkeypatch.setattr(d1.os, "read", changing_read)
    reject(stage, "file_changed")


@pytest.mark.parametrize("kind,code", [("schema", "projection_schema"), ("extra", "field_extra"),
                                       ("missing", "field_missing"), ("input_extra", "field_extra"),
                                       ("digest", "projection_digest"), ("prompt_digest", "projection_digest"),
                                       ("length_bool", "projection_bytes"), ("length_zero", "projection_bytes"),
                                       ("prompt_length", "projection_bytes"), ("packet_pin", "projection_packet_pin"),
                                       ("packet_bytes", "projection_packet_pin"), ("inventory", "projection_inventory")])
def test_projection_drift_and_strict_shape_refused(stage, kind, code):
    projection = stage["projection"]
    if kind == "schema":
        projection["schema"] = "other"
    elif kind == "extra":
        projection["extra"] = False
    elif kind == "missing":
        del projection["inventory"]
    elif kind == "input_extra":
        projection["inputs"]["other"] = {}
    elif kind == "digest":
        projection["inputs"]["label_rules"]["sha256"] = "bad"
    elif kind == "prompt_digest":
        projection["prompt_sha256"] = "bad"
    elif kind == "length_bool":
        projection["inputs"]["packet"]["bytes"] = True
    elif kind == "length_zero":
        projection["inputs"]["format"]["bytes"] = 0
    elif kind == "prompt_length":
        projection["prompt_bytes"] += 1
    elif kind == "packet_pin":
        projection["inputs"]["packet"]["sha256"] = "0" * 64
    elif kind == "packet_bytes":
        projection["inputs"]["packet"]["bytes"] += 1
        projection["prompt_bytes"] += 1
    else:
        projection["inventory"].reverse()
    put(stage["source"] / "projection.json", d1.json_bytes(projection))
    reject(stage, code)


def test_packet_content_drift_refused(stage):
    stage["packet"]["controls"][0]["brief"] += " invented drift"
    put(stage["source"] / "packet.json", d1.json_bytes(stage["packet"]))
    reject(stage, "projection_packet_pin")


@pytest.mark.parametrize("name", ["packet.json", "projection.json"])
def test_packet_and_projection_use_same_file_envelope(stage, tmp_path, name):
    os.link(stage["source"] / name, tmp_path / "extra-link")
    reject(stage, "hardlink")


def test_input_alias_refused(stage):
    reject(stage, "input_alias", raw="packet.json")


def test_all_six_slots_are_separate_and_exclusive(stage):
    for slot in d2.SLOTS:
        assert call(stage, slot=slot)["slot"] == slot
    before = d1.digest((stage["output"] / "A1.validation.json").read_bytes())
    with pytest.raises(d1.Refusal, match="output_collision"):
        call(stage, slot="A1")
    assert d1.digest((stage["output"] / "A1.validation.json").read_bytes()) == before


@pytest.mark.parametrize("slot", ["A0", "A4", "B4", "a1", "../A1", "A1 ", None])
def test_invalid_slot_refused_without_output(stage, slot):
    with pytest.raises(d1.Refusal, match="slot"):
        call(stage, slot=slot)
    assert not tuple(stage["output"].iterdir())


def test_unsafe_output_root_never_written(stage):
    stage["output"].chmod(0o755)
    with pytest.raises(d1.Refusal, match="directory_mode"):
        call(stage)
    assert not tuple(stage["output"].iterdir())


def test_existing_output_symlink_never_followed(stage, tmp_path):
    retained = tmp_path / "retained.json"
    put(retained, b"retained evidence")
    (stage["output"] / "A1.validation.json").symlink_to(retained)
    before = d1.digest(retained.read_bytes())
    with pytest.raises(d1.Refusal, match="output_collision"):
        call(stage)
    assert d1.digest(retained.read_bytes()) == before


def test_validation_schema_and_reason_code_contract(stage):
    schema = json.loads(SCHEMA.read_bytes())
    jsonschema.Draft202012Validator.check_schema(schema)
    assert set(schema["$defs"]["reason"]["enum"]) == set(d2.REASON_CODES)
    validator = jsonschema.Draft202012Validator(schema)
    result = call(stage)
    for key in result:
        incomplete = copy.deepcopy(result)
        del incomplete[key]
        assert not validator.is_valid(incomplete)
    invalid = copy.deepcopy(result)
    invalid["unplanned"] = True
    assert not validator.is_valid(invalid)
    invalid = copy.deepcopy(result)
    invalid.update(verdict="REJECT", reject_reasons=["missing_id"])
    assert not validator.is_valid(invalid)  # decision_ids is forbidden on REJECT.


def test_cli_internal_error_is_refused_without_output(stage, monkeypatch, capsys):
    def crash(*args, **kwargs):
        raise RuntimeError("secret-text")

    monkeypatch.setattr(d2, "validate_slot", crash)
    args = ["--input-root", str(stage["source"]), "--raw", "answer.json", "--packet", "packet.json",
            "--projection", "projection.json", "--slot", "A1", "--output-root", str(stage["output"])]
    assert d2.main(args) == 2
    captured = capsys.readouterr()
    assert "secret-text" not in captured.out
    assert len(captured.out.splitlines()) == 1 and not captured.err
    assert json.loads(captured.out) == {"ok": False, "reject_reasons": ["internal_error"]}
    assert not tuple(stage["output"].iterdir())


def test_cli_pass_and_reject_emit_only_validation_metadata(stage, capsys):
    args = ["--input-root", str(stage["source"]), "--raw", "answer.json", "--packet", "packet.json",
            "--projection", "projection.json", "--slot", "A1", "--output-root", str(stage["output"])]
    assert d2.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert set(result) == {"schema", "slot", "raw_sha256", "raw_bytes", "packet_sha256", "verdict",
                           "reject_reasons", "decision_ids"}
    answer(stage, raw=b"invalid")
    args[args.index("A1")] = "B1"
    assert d2.main(args) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["verdict"] == "REJECT"
    assert "decision_ids" not in result
