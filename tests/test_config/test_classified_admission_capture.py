"""Owned temporary files only: exact classified identity is NOT a launch."""
import base64
import hashlib
from types import SimpleNamespace

import pytest

from temper_ai.config import admission_capture
from temper_ai.config.admission_capture import capture_classified_record
from temper_ai.config.admission_contract import AdmissionRefused, RefusalCode
from temper_ai.config.store import ConfigStore
from temper_ai.spawner import box_guard
from tests.test_config.admission_cases import text, typed_case

DATA = b"# byte identity, including this comment\nschema_version: '1.0'\nagent:\n  name: owned\n  type: script\n  script_template: 'printf static'\n"
CONFIG = {"schema_version": "1.0", "agent": {"name": "owned", "type": "script", "script_template": "printf static"}}
RELATIVE = "configs/agents/owned.yaml"


@pytest.fixture(autouse=True)
def reset_guard():
    box_guard.reset()
    yield
    box_guard.reset()


def activate(tmp_path, data=DATA):
    file = tmp_path / "agents" / "owned.yaml"
    file.parent.mkdir(exist_ok=True)
    file.write_bytes(data)
    profile = {"boundary": "sealed", "launch": {
        "workflow": "synthetic",
        "files": {RELATIVE: hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()},
        "configs": {"agent": {"owned": RELATIVE}}, "allowed": {},
    }}
    return file, profile, box_guard.activate(profile, tmp_path)


def capture(guard):
    _, codec, _, _, _, _ = typed_case()
    return capture_classified_record(codec, guard=guard, name="owned", config_type="agent", launch_id="synthetic-launch")


def test_classified_happy_path_binds_original_checked_bytes_not_db_or_reread(tmp_path, monkeypatch):
    file, profile, guard = activate(tmp_path)
    # Changing the authoring path after activation must not replace the checked bytes.
    file.write_bytes(b"changed on disk, never reopened")
    profile["launch"]["configs"]["agent"]["owned"] = "configs/other.yaml"
    def no_db(*args, **kwargs):
        raise AssertionError("classified capture must never load DB")
    monkeypatch.setattr(ConfigStore, "get", no_db)
    monkeypatch.setattr(ConfigStore, "get_raw_record", no_db)
    record = capture(guard)
    value = record.value()
    assert value["config_json"] == text(CONFIG)
    assert base64.b64decode(value["file_base64"]) == DATA
    assert value["origin"] == {"kind": "classified_file", "relative_path": RELATIVE,
                               "launch_id": "synthetic-launch", "file_sha256": hashlib.sha256(DATA).hexdigest(),
                               "git_blob_sha1": hashlib.sha1(b"blob " + str(len(DATA)).encode() + b"\0" + DATA).hexdigest()}
    value["config_json"] = "{}"
    assert record.value()["config_json"] == text(CONFIG)
    # Same parsed config, different comment bytes, is a different raw identity.
    _, _, second = activate(tmp_path, DATA + b"# second authoring identity\n")
    assert capture(second).sha256 != record.sha256


@pytest.mark.parametrize("data,code", [
    (b"agent: {name: a, name: b}\n", RefusalCode.DUPLICATE),
    (b"a: &a {x: 1}\nb: *a\n", RefusalCode.ALIAS),
    (b"a: &a scalar\nb: *a\n", RefusalCode.ALIAS),
    (b"a: &a [*a]\n", RefusalCode.ALIAS),
    (b"a: &a {x: 1}\nb: {<<: *a}\n", RefusalCode.ALIAS),
    (b"1: value\n", RefusalCode.TYPE),
    (b"[plain, list]\n", RefusalCode.TYPE),
    (b"date: 2026-01-01\n", RefusalCode.TYPE),
    (b"value: .inf\n", RefusalCode.NONFINITE),
    (b"schema_version: '9.0'\n", RefusalCode.VERSION),
    (b"schema_version: 1.0\n", RefusalCode.VERSION),
    (b"\xff\xfe", RefusalCode.JSON),
    (b"agent: [\n", RefusalCode.JSON),
])
def test_classified_duplicate_alias_type_and_parse_refusals_never_fall_back(tmp_path, monkeypatch, data, code):
    _, _, guard = activate(tmp_path, data)
    def no_fallback(*args, **kwargs):
        raise AssertionError("no fallback on any parse refusal")
    monkeypatch.setattr(ConfigStore, "get", no_fallback)
    monkeypatch.setattr(ConfigStore, "get_raw_record", no_fallback)
    with pytest.raises(AdmissionRefused) as exc:
        capture(guard)
    assert exc.value.code == code and str(exc.value) == code.value
    assert exc.value.__suppress_context__ or exc.value.__context__ is None


def test_guard_original_source_blob_and_access_checks_remain(tmp_path, monkeypatch):
    file, profile, guard = activate(tmp_path)
    _, codec, _, _, _, _ = typed_case()
    with pytest.raises(AdmissionRefused, match="^outside_closure$"):
        capture_classified_record(codec, guard=guard, name="not-in-launch", config_type="agent", launch_id="synthetic")
    guard.configs["agent"]["owned"] = "configs/agents/other.yaml"
    with pytest.raises(AdmissionRefused, match="^outside_closure$"):
        capture(guard)
    guard.configs["agent"]["owned"] = RELATIVE
    guard.files[RELATIVE] = DATA + b"# substituted checked mapping\n"
    with pytest.raises(AdmissionRefused, match="^source_origin$"):
        capture(guard)
    box_guard.reset()
    with pytest.raises(AdmissionRefused, match="^source_origin$"):
        capture(guard)
    forged = SimpleNamespace(raw_config_record=lambda *args: (RELATIVE, DATA))
    with pytest.raises(AdmissionRefused, match="^source_origin$"):
        capture(forged)
    file.write_bytes(b"changed after classification")
    with pytest.raises(box_guard.LaunchRefused):
        box_guard.activate(profile, tmp_path)


def test_size_depth_and_node_count_reuse_existing_limits(tmp_path, monkeypatch):
    _, _, guard = activate(tmp_path)
    monkeypatch.setattr(box_guard, "MAX_CONFIG_SIZE", 1)
    with pytest.raises(AdmissionRefused, match="^source_origin$"):
        capture(guard)
    monkeypatch.undo()
    monkeypatch.setattr(admission_capture, "MAX_YAML_NESTING_DEPTH", 1)
    with pytest.raises(AdmissionRefused, match="^wire_schema$"):
        capture(guard)
    monkeypatch.undo()
    monkeypatch.setattr(admission_capture, "MAX_YAML_NODES", 1)
    with pytest.raises(AdmissionRefused, match="^wire_schema$"):
        capture(guard)


def test_classified_boundaries_have_guard_removal_bites(tmp_path, monkeypatch):
    _, _, guard = activate(tmp_path)
    guard.files[RELATIVE] = DATA + b"# changed\n"
    with pytest.raises(AdmissionRefused, match="^source_origin$"):
        capture(guard)
    # Removing the retained source identity boundary would accept the mutation.
    monkeypatch.setattr(box_guard.Guard, "raw_config_record", lambda self, *args: (RELATIVE, self.files[RELATIVE]))
    assert base64.b64decode(capture(guard).value()["file_base64"]) != DATA
    _, _, duplicate = activate(tmp_path, b"name: a\nname: b\n")
    with pytest.raises(AdmissionRefused, match="^duplicate_key$"):
        capture(duplicate)
    import yaml
    monkeypatch.setattr(admission_capture, "_parse_classified", yaml.safe_load)
    assert capture(duplicate).value()["config_json"] == '{"name":"b"}'
