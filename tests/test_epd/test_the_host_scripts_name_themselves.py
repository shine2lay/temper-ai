"""The loop's host scripts name themselves to temper on every write (temper queue #45, 2026-10-05).

temper counts each write under its caller's name (docs/api-access.md). A write without a key is an
unknown caller: logged today, refused with a 401 once temper enforces. The driver's writes (start a
run, fork one) and push_configs' PUT send the autopilot's key, read from its file at each write:
TEMPER_API_KEY_FILE, else ~/.config/temper/api-keys/autopilot.key. The key is never printed. Inside
a box the file isn't there; the driver must not need it, so the write goes out unnamed and nothing
fails.
"""

import io
import json
from pathlib import Path

from tests.test_epd import test_epd_loop

# The driver, loaded with its state in a temporary directory: test_epd_loop's fixture, by name.
L = test_epd_loop.L

KEY = "a-test-key-not-a-real-one"


def sent_requests(L, monkeypatch, reply: dict) -> list:
    """Stub the HTTP call; return the list every request the driver makes is put on."""
    sent = []

    def urlopen(req, timeout=None):
        sent.append(req)
        return io.BytesIO(json.dumps(reply).encode())

    monkeypatch.setattr(L.urllib.request, "urlopen", urlopen)
    return sent


def headers(req) -> dict:
    return {k.lower(): v for k, v in req.header_items()}


def test_starting_and_forking_a_run_send_the_autopilot_key(L, tmp_path, monkeypatch, capsys):
    key_file = tmp_path / "autopilot.key"
    key_file.write_text(KEY + "\n")
    monkeypatch.setenv("TEMPER_API_KEY_FILE", str(key_file))
    sent = sent_requests(L, monkeypatch, {"execution_id": "run-1"})

    assert L.post_run("epd_loop", {"bet_id": "b001"}, "/ws") == "run-1"
    assert L.fork_run("run-0", 3, "epd_loop", {"bet_id": "b001"}, "/ws") == "run-1"

    assert [r.full_url.rsplit("/api/", 1)[1] for r in sent] == ["runs", "runs/fork"]
    for req in sent:
        assert headers(req)["authorization"] == f"Bearer {KEY}"
        assert headers(req)["content-type"] == "application/json"
    out = capsys.readouterr()
    assert KEY not in out.out + out.err


def test_the_key_is_read_at_each_write(L, tmp_path, monkeypatch):
    key_file = tmp_path / "autopilot.key"
    monkeypatch.setenv("TEMPER_API_KEY_FILE", str(key_file))
    key_file.write_text("old-key")
    assert L.api_headers()["Authorization"] == "Bearer old-key"
    key_file.write_text("new-key")  # a rotated key is used by the next write, with no restart
    assert L.api_headers()["Authorization"] == "Bearer new-key"


def test_without_the_key_file_a_write_goes_out_unnamed(L, tmp_path, monkeypatch):
    """In a box (or before the key exists) the file isn't there: nothing fails, nothing is named."""
    monkeypatch.setenv("TEMPER_API_KEY_FILE", str(tmp_path / "missing.key"))
    sent = sent_requests(L, monkeypatch, {"execution_id": "run-2"})

    assert L.post_run("epd_loop", {}, "/ws") == "run-2"
    assert "authorization" not in headers(sent[0])


def test_the_default_key_file_is_the_autopilots(L, monkeypatch):
    monkeypatch.delenv("TEMPER_API_KEY_FILE", raising=False)
    assert L.API_KEY_FILE == Path.home() / ".config" / "temper" / "api-keys" / "autopilot.key"


def test_a_request_id_ties_the_write_to_the_callers_log(L, tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPER_API_KEY_FILE", str(tmp_path / "missing.key"))
    assert L.api_headers("approve_pr-1234")["X-Request-ID"] == "approve_pr-1234"
    assert "X-Request-ID" not in L.api_headers()
