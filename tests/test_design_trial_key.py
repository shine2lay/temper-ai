"""design_trial.py names the design role on temper's write guard (docs/api-access.md).

Starts send the design key read at call time (TEMPER_API_KEY_FILE, else the default key file);
with no readable key they go without one, and reads never carry it.
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "configs/design/bin/design_trial.py"
spec = importlib.util.spec_from_file_location("design_trial_under_test", SCRIPT)
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class _Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def sent(monkeypatch):
    """Every request design_trial hands to urlopen; no network."""
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        if isinstance(req, str):  # _wait's read
            return _Reply(json.dumps({"status": "completed"}).encode())
        return _Reply(json.dumps({"execution_id": "run-1"}).encode())

    monkeypatch.setattr(trial.urllib.request, "urlopen", fake_urlopen)
    return calls


def test_a_start_sends_the_named_key(tmp_path, monkeypatch, sent, capsys):
    key = tmp_path / "design.key"
    key.write_text("k-test-123\n")
    monkeypatch.setenv("TEMPER_API_KEY_FILE", str(key))

    assert trial._post_run("design_review", tmp_path, {"brief": "b"}) == "run-1"

    req = sent[0]
    assert req.get_method() == "POST"
    assert req.get_header("Authorization") == "Bearer k-test-123"
    assert req.get_header("Content-type") == "application/json"
    assert json.loads(req.data) == {
        "workflow": "design_review",
        "workspace_path": str(tmp_path),
        "inputs": {"brief": "b"},
    }
    out = capsys.readouterr()
    assert "k-test-123" not in out.out + out.err


def test_the_default_key_file_is_used_without_the_env(tmp_path, monkeypatch, sent):
    key = tmp_path / "default.key"
    key.write_text("k-default")
    monkeypatch.delenv("TEMPER_API_KEY_FILE", raising=False)
    monkeypatch.setattr(trial, "DEFAULT_KEY_FILE", key)

    trial._post_run("design_review", tmp_path, {})

    assert sent[0].get_header("Authorization") == "Bearer k-default"


@pytest.mark.parametrize(
    "content", [None, "", "  \n"], ids=["missing", "empty", "blank"]
)
def test_no_readable_key_sends_no_header(tmp_path, monkeypatch, sent, content):
    key = tmp_path / "design.key"
    if content is not None:
        key.write_text(content)
    monkeypatch.setenv("TEMPER_API_KEY_FILE", str(key))

    assert trial._post_run("design_review", tmp_path, {}) == "run-1"

    assert not sent[0].has_header("Authorization")


def test_reads_carry_no_key(tmp_path, monkeypatch, sent):
    key = tmp_path / "design.key"
    key.write_text("k-test")
    monkeypatch.setenv("TEMPER_API_KEY_FILE", str(key))

    assert trial._wait("run-1")["status"] == "completed"

    assert isinstance(sent[0], str)  # a plain GET by URL: no headers at all
