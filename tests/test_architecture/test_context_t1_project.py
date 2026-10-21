"""D1 standalone synthetic cases. No real packet, expected key, route or model.

H-T1-D12-1: a pinned exact-byte projection is a deterministic input boundary.
Pass: invented Unicode/quotes, every profile section plus a joint-section case,
exact bytes/IDs/order. Refuse: leaks, extra fields/files, duplicate IDs,
truncation/normalization and unsafe file/path envelopes. Hash assertions avoid
printing constructed prompt bytes, including on a test failure.
"""
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
FIXTURES = Path(__file__).parent / "fixtures/context_t1/project_validate"
SCHEMA = REPO / "configs/architecture/stages/context_profile/t1/projection.v1.schema.json"


def put(path, raw):
    path.write_bytes(raw)
    path.chmod(0o600)


@pytest.fixture
def stage(tmp_path):
    source, output = tmp_path / "input", tmp_path / "output"
    source.mkdir(mode=0o700)
    output.mkdir(mode=0o700)
    originals = {}
    for name in ("packet.json", "rules.txt", "format.txt"):
        raw = (FIXTURES / name).read_bytes()
        originals[name] = raw
        put(source / name, raw)
    return {"source": source, "output": output, "originals": originals}


def call(stage, **changes):
    options = dict(input_root=stage["source"], packet="packet.json",
                   packet_sha256=d1.digest(stage["originals"]["packet.json"]),
                   label_rules="rules.txt", label_rules_sha256=d1.digest(stage["originals"]["rules.txt"]),
                   format_file="format.txt", format_sha256=d1.digest(stage["originals"]["format.txt"]),
                   output_root=stage["output"])
    options.update(changes)
    return d1.project(**options)


def packet(stage):
    return json.loads(stage["originals"]["packet.json"])


def replace_packet(stage, value):
    raw = d1.json_bytes(value)
    stage["originals"]["packet.json"] = raw
    put(stage["source"] / "packet.json", raw)


def refused(stage, code, **changes):
    with pytest.raises(d1.Refusal) as error:
        call(stage, **changes)
    assert error.value.code == code
    assert not tuple(stage["output"].iterdir())


def test_unicode_quotes_all_sections_joint_case_exact_bytes_ids_order(stage):
    result = call(stage)
    original = packet(stage)
    assert set(original["controls"][0]["profile"]) >= {
        "maturity", "facts", "constraints", "unknowns", "observed", "materiality", "relation"}
    assert original["controls"][1]["path"] == "/relation"
    assert result["inventory"] == [{"id": row["id"], "path": row["path"]}
                                   for row in original["controls"]]
    # Independent fixed transport framing; never compare/output a prompt body.
    expected = (b"Return one strict JSON object in the supplied format.\n"
                b"The following documents are the complete task input.\n\nLABEL-RULES-v2.md\n"
                + stage["originals"]["rules.txt"] + b"\n\npacket/FORMAT.md\n"
                + stage["originals"]["format.txt"] + b"\n\npacket/PACKET.json\n"
                + stage["originals"]["packet.json"])
    prompt_raw = (stage["output"] / "prompt.txt").read_bytes()
    assert d1.digest(prompt_raw) == d1.digest(expected)
    assert result["prompt_sha256"] == d1.digest(expected)
    assert result["prompt_bytes"] == len(expected)
    assert result["inputs"] == {
        name: {"sha256": d1.digest(stage["originals"][file]), "bytes": len(stage["originals"][file])}
        for name, file in (("packet", "packet.json"), ("label_rules", "rules.txt"), ("format", "format.txt"))}
    assert d1.strict_json((stage["output"] / "projection.json").read_bytes()) == result
    for path in stage["output"].iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.stat().st_nlink == 1
    schema = json.loads(SCHEMA.read_bytes())
    jsonschema.Draft202012Validator.check_schema(schema)
    assert jsonschema.Draft202012Validator(schema).is_valid(result)


@pytest.mark.parametrize("pin", ["packet_sha256", "label_rules_sha256", "format_sha256"])
def test_wrong_pin_refused(stage, pin):
    refused(stage, "pin_mismatch", **{pin: "0" * 64})


@pytest.mark.parametrize("pin", [None, "", "a" * 63, "A" * 64, 17])
def test_pin_format_not_coerced(stage, pin):
    refused(stage, "pin_mismatch", packet_sha256=pin)


@pytest.mark.parametrize("change", ["truncate", "unicode_normalize", "line_endings"])
def test_truncation_and_normalization_refused(stage, change):
    target = "rules.txt" if change == "line_endings" else "packet.json"
    raw = stage["originals"][target]
    if change == "truncate":
        raw = raw[:-7]
    elif change == "unicode_normalize":
        raw = raw.replace("café".encode(), "café".encode())
    else:
        raw = raw.replace(b"\n", b"\r\n")
    put(stage["source"] / target, raw)
    refused(stage, "pin_mismatch")


@pytest.mark.parametrize("location", ["top_extra", "top_missing", "row_extra", "row_missing"])
def test_extra_missing_packet_fields_refused(stage, location):
    value = packet(stage)
    if location == "top_extra":
        value["unplanned"] = True
    elif location == "top_missing":
        del value["schema"]
    elif location == "row_extra":
        value["controls"][0]["unplanned"] = True
    else:
        del value["controls"][0]["brief"]
    replace_packet(stage, value)
    refused(stage, "field_extra" if location.endswith("extra") else "field_missing")


@pytest.mark.parametrize("marker", ["label", "labels", "family", "expected", "key", "decision",
                                    "counts", "class_counts", "report", "expectedCount", "LABEL"])
@pytest.mark.parametrize("where", ["top", "profile"])
def test_key_labels_counts_report_leaks_refused(stage, marker, where):
    value = packet(stage)
    destination = value if where == "top" else value["controls"][0]["profile"]
    destination[marker] = "synthetic forbidden marker"
    replace_packet(stage, value)
    refused(stage, "leak_marker")


def test_candidate_decisions_content_refused(stage):
    value = packet(stage)
    value["controls"][0]["brief"] = 'synthetic candidate-decisions/v2 content'
    replace_packet(stage, value)
    refused(stage, "leak_marker")


def test_extra_input_file_refused_without_reading_any_file(stage, monkeypatch):
    put(stage["source"] / "unexpected.txt", b"invented extra")

    def do_not_read(*_args):
        pytest.fail("extra input file must fail before reading any content")

    monkeypatch.setattr(d1.PrivateRoot, "read_bytes", do_not_read)
    refused(stage, "input_file_set")


def test_missing_input_file_refused(stage):
    (stage["source"] / "format.txt").unlink()
    refused(stage, "input_file_set")


def test_duplicate_id_refused(stage):
    value = packet(stage)
    value["controls"].append(value["controls"][0])
    replace_packet(stage, value)
    refused(stage, "duplicate_id")


@pytest.mark.parametrize("path", ["facts/0", "/facts/01", "/facts/-1", "/facts/9", "/facts/~3", "/absent"])
def test_wrong_pointer_refused(stage, path):
    value = packet(stage)
    value["controls"][0]["path"] = path
    replace_packet(stage, value)
    refused(stage, "pointer")


@pytest.mark.parametrize("value", [None, [], "wrong", 1])
def test_profile_type_refused(stage, value):
    data = packet(stage)
    data["controls"][0]["profile"] = value
    replace_packet(stage, data)
    refused(stage, "packet_control")


@pytest.mark.parametrize("kind,code", [("schema", "packet_schema"), ("empty_controls", "packet_schema"),
                                       ("controls_type", "packet_schema"), ("row_type", "field_type"),
                                       ("blank_id", "packet_control"), ("blank_brief", "packet_control")])
def test_packet_structure_refused(stage, kind, code):
    value = packet(stage)
    if kind == "schema":
        value["schema"] = "other"
    elif kind == "empty_controls":
        value["controls"] = []
    elif kind == "controls_type":
        value["controls"] = {}
    elif kind == "row_type":
        value["controls"][0] = []
    elif kind == "blank_id":
        value["controls"][0]["id"] = " "
    else:
        value["controls"][0]["brief"] = " "
    replace_packet(stage, value)
    refused(stage, code)


@pytest.mark.parametrize("kind,code", [("duplicate_nested", "duplicate_json_key"), ("nan", "nan"),
                                       ("infinity", "infinity"), ("overflow", "overflow_nonfinite"),
                                       ("bom", "bom"), ("utf8", "invalid_utf8"),
                                       ("trailing", "trailing_data"), ("malformed", "malformed_json")])
def test_packet_parser_refused_even_with_matching_pin(stage, kind, code):
    raw = stage["originals"]["packet.json"]
    if kind == "duplicate_nested":
        raw = raw.replace(b'"name":', b'"name":"duplicate","name":', 1)
    elif kind in ("nan", "infinity", "overflow"):
        literal = {"nan": b"NaN", "infinity": b"Infinity", "overflow": b"1e9999"}[kind]
        raw = b'{"number":' + literal + b'}'
    elif kind == "bom":
        raw = b"\xef\xbb\xbf" + raw
    elif kind == "utf8":
        raw = b"\xff"
    elif kind == "trailing":
        raw += b"{}"
    else:
        raw = b"{"
    stage["originals"]["packet.json"] = raw
    put(stage["source"] / "packet.json", raw)
    refused(stage, code)


def test_escaped_pointer_and_nested_object_pass(stage):
    value = packet(stage)
    value["controls"][0]["profile"]["a/b~c"] = {"nested": ["invented leaf"]}
    value["controls"][0]["path"] = "/a~1b~0c/nested/0"
    replace_packet(stage, value)
    assert call(stage)["inventory"][0]["path"] == "/a~1b~0c/nested/0"


@pytest.mark.parametrize("path", ["../packet.json", "/packet.json", "a/../packet.json", "a//packet.json",
                                  "./packet.json", "a\\packet.json", "packet.json\x00"])
def test_unsafe_path_refused(stage, path):
    refused(stage, "path", packet=path)


@pytest.mark.parametrize("kind,code", [("symlink", "symlink"), ("hardlink", "hardlink"),
                                       ("fifo", "file_type"), ("directory", "file_type"),
                                       ("mode", "file_mode"), ("oversize", "size")])
def test_unsafe_file_envelope_refused(stage, tmp_path, kind, code):
    target = stage["source"] / "packet.json"
    if kind == "symlink":
        other = tmp_path / "target.json"
        put(other, stage["originals"]["packet.json"])
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
        target.chmod(0o640)
    else:
        put(target, b"x" * (d1.MAX_BYTES + 1))
    refused(stage, code)


@pytest.mark.parametrize("which", ["input", "output"])
def test_nonprivate_root_refused(stage, which):
    stage["source" if which == "input" else "output"].chmod(0o750)
    refused(stage, "directory_mode")


def test_symlink_root_refused(stage, tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(stage["source"], target_is_directory=True)
    refused(stage, "symlink", input_root=alias)


@pytest.mark.parametrize("kind", ["symlink", "mode"])
def test_nested_directory_envelope_refused(stage, tmp_path, kind):
    nested = stage["source"] / "nested"
    if kind == "symlink":
        target = tmp_path / "external"
        target.mkdir(mode=0o700)
        nested.symlink_to(target, target_is_directory=True)
    else:
        nested.mkdir(mode=0o750)
    for name in stage["originals"]:
        (stage["source"] / name).rename(nested / name)
    refused(stage, "symlink" if kind == "symlink" else "directory_mode", packet="nested/packet.json",
            label_rules="nested/rules.txt", format_file="nested/format.txt")


def test_nested_private_directory_pass(stage):
    nested = stage["source"] / "nested"
    nested.mkdir(mode=0o700)
    for name in stage["originals"]:
        (stage["source"] / name).rename(nested / name)
    assert call(stage, packet="nested/packet.json", label_rules="nested/rules.txt",
                format_file="nested/format.txt")["schema"] == d1.PROJECTION_SCHEMA


def test_file_changed_during_read_refused(stage, monkeypatch):
    read = d1.os.read
    changed = False

    def changing_read(fd, amount):
        nonlocal changed
        data = read(fd, amount)
        if data and not changed:
            changed = True
            with (stage["source"] / "packet.json").open("ab") as stream:
                stream.write(b" ")
        return data

    monkeypatch.setattr(d1.os, "read", changing_read)
    refused(stage, "file_changed")


def test_output_collision_refused_without_overwrite(stage):
    put(stage["output"] / "prompt.txt", b"retained synthetic evidence")
    before = d1.digest((stage["output"] / "prompt.txt").read_bytes())
    with pytest.raises(d1.Refusal, match="output_not_empty"):
        call(stage)
    assert d1.digest((stage["output"] / "prompt.txt").read_bytes()) == before
    with d1.PrivateRoot(stage["output"]) as output, pytest.raises(d1.Refusal, match="output_collision"):
        output.write_new("prompt.txt", b"replacement")
    assert d1.digest((stage["output"] / "prompt.txt").read_bytes()) == before


def test_output_modes_independent_of_umask(stage):
    before = os.umask(0o777)
    try:
        call(stage)
    finally:
        os.umask(before)
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in stage["output"].iterdir())


@pytest.mark.parametrize("over", [False, True], ids=["maximum", "over_maximum"])
def test_projected_prompt_size_boundary(stage, over):
    size = d1.MAX_BYTES - d1.FRAMING_BYTES - len(stage["originals"]["packet.json"]) - len(stage["originals"]["format.txt"])
    raw = b"x" * (size + int(over))
    stage["originals"]["rules.txt"] = raw
    put(stage["source"] / "rules.txt", raw)
    if over:
        refused(stage, "size")
    else:
        assert call(stage)["prompt_bytes"] == d1.MAX_BYTES


@pytest.mark.parametrize("document", ["rules.txt", "format.txt"])
@pytest.mark.parametrize("raw,code", [(b"\xff", "invalid_utf8"), (b"\xef\xbb\xbftext", "bom")], ids=["invalid_utf8", "bom"])
def test_protocol_encoding_refused_even_with_matching_pin(stage, document, raw, code):
    stage["originals"][document] = raw
    put(stage["source"] / document, raw)
    refused(stage, code)


@pytest.mark.parametrize("document", ["rules.txt", "format.txt"])
def test_empty_protocol_refused(stage, document):
    stage["originals"][document] = b""
    put(stage["source"] / document, b"")
    refused(stage, "empty_input")


def test_cli_metadata_only_and_extra_file_argument_refused(stage, capsys):
    args = ["--input-root", str(stage["source"]), "--packet", "packet.json", "--packet-sha256",
            d1.digest(stage["originals"]["packet.json"]), "--label-rules", "rules.txt", "--label-rules-sha256",
            d1.digest(stage["originals"]["rules.txt"]), "--format", "format.txt", "--format-sha256",
            d1.digest(stage["originals"]["format.txt"]), "--output-root", str(stage["output"])]
    with pytest.raises(SystemExit) as error:
        d1.main([*args, "--extra-file", "unplanned.txt"])
    assert error.value.code == 2
    capsys.readouterr()
    assert d1.main(args) == 0
    metadata = json.loads(capsys.readouterr().out)
    assert set(metadata) == {"schema", "inputs", "inventory", "prompt_sha256", "prompt_bytes"}
