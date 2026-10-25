"""Deterministic capture contracts; browser fixtures are exercised on temper-dev separately."""
import base64
import copy
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("capture_v2", ROOT / "configs/design/bin/design_web_capture.py")
wc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wc)
VIEW = {"name": "small", "width": 24, "height": 40}


def observation(height=83):
    return {
        "url": "https://example.com/", "title": "A useful homepage", "document_height": height,
        "text_nodes": [{"id": "a", "text": "A useful homepage", "tag": "h1", "bbox": [1, 1, 20, 12],
                        "visibility": "visible", "slice_index": 1, "slice_indices": [1]}],
        "images": [], "metrics": {"h1_count": 1, "main_chars": 150, "body_chars": 150, "graphic_area": 0},
    }


def source():
    pixels = bytes([10, 70, 120]) * (VIEW["width"] * 83)
    first = wc.encode_png(VIEW["width"], VIEW["height"], pixels[:VIEW["width"] * VIEW["height"] * 3])
    full = wc.encode_png(VIEW["width"], 83, pixels)
    obs = observation()
    return {
        "viewport": VIEW, "requested_url": "https://example.com/", "final_url": "https://example.com/",
        "http_status": 200, "ok": True, "csp_bypass": False, "context_closed": True, "device_scale_factor": 1,
        "cut_off": False, "cookie": {"action": "no cookie window found", "clicks": []}, "scroll_steps": [],
        "first_screen": {"png_base64": base64.b64encode(first).decode(), "before": copy.deepcopy(obs),
                         "coherent": True, "captured_at": "2026-10-24T00:00:00Z"},
        "full_page": {"png_base64": base64.b64encode(full).decode(), "before": obs,
                      "text": obs["text_nodes"], "coherent": True},
    }


def stored(tmp_path):
    record = wc.store_capture_record(tmp_path, VIEW, source())
    request = wc.request_config("https://example.com/", views=[VIEW])
    return record, request


@pytest.mark.parametrize("url", ["https://example.com/", "http://example.org/a?b=c", "https://8.8.8.8/"])
def test_public_urls(url):
    assert wc.public_url(url) == url


@pytest.mark.parametrize("url", ["file:///tmp/a", "http://localhost/", "http://127.0.0.1/", "http://10.0.0.2/",
                                  "http://metadata.internal/", "https://user:pass@example.com/", "not a URL",
                                  "http://[::1]/", "http://192.168.1.1/", "http://127.1/"])
def test_reject_private_urls(url):
    with pytest.raises(ValueError):
        wc.public_url(url)


@pytest.mark.parametrize("views", [[], [{"name": "../x", "width": 1, "height": 2}],
                                     [{"name": "x", "width": 0, "height": 2}], [VIEW, VIEW],
                                     [{"name": "x", "width": True, "height": 2}]])
def test_viewport_contract(views):
    with pytest.raises(ValueError):
        wc.request_config("https://example.com", views=views)


@pytest.mark.parametrize("width,height", [(1, 1), (390, 844), (7, 83)])
def test_png_round_trip(width, height):
    pixels = bytes([12, 87, 200]) * (width * height)
    assert wc.decode_png(wc.encode_png(width, height, pixels)) == (width, height, pixels)


@pytest.mark.parametrize("mutation", ["crc", "truncated", "trailing", "signature"])
def test_png_corruption_refused(mutation):
    raw = wc.encode_png(3, 3, bytes([12, 1, 2]) * 9)
    bad = {"crc": raw[:20] + bytes([raw[20] ^ 1]) + raw[21:], "truncated": raw[:-4],
           "trailing": raw + b"bad", "signature": b"not PNG"}[mutation]
    with pytest.raises(ValueError):
        wc.decode_png(bad)


def test_exact_slices_and_short_last_slice(tmp_path):
    record, request = stored(tmp_path)
    result = wc.verify_view(tmp_path, record, VIEW, request)
    assert result["status"] == "usable"
    assert [s["height"] for s in result["views"]["full_page"]["slices"]] == [40, 40, 3]
    assert result["views"]["full_page"]["slices_pixel_exact"]


@pytest.mark.parametrize("mutation", ["hash", "slice_gap", "slice_missing", "text_index", "accept", "cleanup", "viewport"])
def test_verify_rejects_broken_contract(tmp_path, mutation):
    record, request = stored(tmp_path)
    if mutation == "hash":
        record["full_page"]["image"]["sha256"] = "0" * 64
    elif mutation == "slice_gap":
        record["full_page"]["slices"][1]["y"] += 1
    elif mutation == "slice_missing":
        record["full_page"]["slices"].pop()
    elif mutation == "text_index":
        entry = record["full_page"]["text_artifact"]
        text = json.loads((tmp_path / entry["file"]).read_text())
        text["text_nodes"][0]["slice_index"] = 2
        raw = json.dumps(text).encode()
        (tmp_path / entry["file"]).write_bytes(raw)
        entry.update(sha256=wc.digest(raw), bytes=len(raw))
    elif mutation == "accept":
        record["cookie"]["clicks"] = [{"label": "accept all"}]
    elif mutation == "cleanup":
        record["context_closed"] = False
    else:
        record["viewport"] = {**VIEW, "height": 41}
    with pytest.raises(ValueError):
        wc.verify_view(tmp_path, record, VIEW, request)


@pytest.mark.parametrize("label", sorted(wc.REJECT_LABELS))
def test_allowlist_is_reject_only(tmp_path, label):
    record, request = stored(tmp_path)
    record["cookie"]["clicks"] = [{"label": label, "clicked_at": "2026-10-24T00:00:01Z"}]
    assert wc.verify_view(tmp_path, record, VIEW, request)["status"] == "usable"


@pytest.mark.parametrize("field,value,status", [("http_status", 403, "not usable"), ("error", "Timeout", "not usable"),
                                                ("cut_off", True, "incomplete")])
def test_diagnostics_never_promoted(tmp_path, field, value, status):
    record, request = stored(tmp_path)
    record[field] = value
    assert wc.verify_view(tmp_path, record, VIEW, request)["status"] == status


def test_cookie_without_reject_is_uncertain(tmp_path):
    record, request = stored(tmp_path)
    record["cookie"]["action"] = "cookie window left open"
    assert wc.verify_view(tmp_path, record, VIEW, request)["status"] == "uncertain"


def test_old_airbnb_shell_is_incomplete_but_short_complete_is_not():
    pixels = bytes([255, 255, 255]) * 24 * 40
    shell = {"metrics": {"body_chars": 1600, "main_chars": 0, "h1_count": 0}}
    assert wc.incomplete_measurements(24, 40, pixels, shell, 40)["reasons"]
    assert not wc.incomplete_measurements(24, 40, pixels, observation(), 40)["reasons"]


def test_broken_image_is_incomplete():
    obs = observation()
    obs["images"] = [{"bbox": [2, 2, 10, 10], "complete": True, "natural_width": 0}]
    result = wc.incomplete_measurements(24, 40, bytes(24 * 40 * 3), obs, 40)
    assert result["unloaded_images"] and result["reasons"]


@pytest.mark.parametrize("bbox", [[30, 2, 10, 10], [-20, 2, 10, 10], [2, 45, 10, 10]])
def test_images_outside_the_picture_do_not_count(bbox):
    # R11: right of the column (carousel), left of it, or below a one-screen picture (far lazy image).
    obs = observation()
    obs["images"] = [{"bbox": bbox, "complete": False, "natural_width": 0}]
    result = wc.incomplete_measurements(24, 40, bytes([10, 70, 120]) * (24 * 40), obs, 40)
    assert not result["unloaded_images"] and not result["reasons"]


def bracketed(tmp_path, change):
    data = source()
    after = copy.deepcopy(data["full_page"]["before"])
    extra = {"id": "z", "text": "Off to the side", "tag": "p", "bbox": [-90, 50, 30, 10], "visibility": "visible",
             "slice_index": 2, "slice_indices": [2]}
    data["full_page"]["before"]["text_nodes"].append(copy.deepcopy(extra))
    after["text_nodes"].append(extra)
    change(after)
    data["full_page"]["after"] = after
    record = wc.store_capture_record(tmp_path, VIEW, data)
    return wc.verify_view(tmp_path, record, VIEW, wc.request_config("https://example.com/", views=[VIEW]))


def test_wording_change_in_picture_is_uncertain(tmp_path):
    result = bracketed(tmp_path, lambda a: a["text_nodes"][0].update(text="Live count 2"))
    assert result["status"] == "uncertain"
    text = json.loads((tmp_path / result["views"]["full_page"]["text"]["file"]).read_text())
    assert text["text_nodes"][0]["changed_during_capture"] and text["bracket"]["material"] == ["a"]


def test_sideways_move_in_same_slice_is_a_note(tmp_path):
    result = bracketed(tmp_path, lambda a: a["text_nodes"][0].update(bbox=[3, 1, 20, 12]))
    assert result["status"] == "usable"
    assert any("moved within the same slice" in n for n in result["views"]["full_page"]["notes"])


def test_change_outside_picture_is_ignored(tmp_path):
    result = bracketed(tmp_path, lambda a: a["text_nodes"][1].update(text="Other words", bbox=[-80, 50, 30, 10]))
    assert result["status"] == "usable"
    assert any("outside the picture" in n for n in result["views"]["full_page"]["notes"])


def test_page_height_change_is_uncertain(tmp_path):
    result = bracketed(tmp_path, lambda a: a.update(document_height=120))
    assert result["status"] == "uncertain"


def test_forged_bracket_record_is_refused(tmp_path):
    data = source()
    data["full_page"]["after"] = copy.deepcopy(data["full_page"]["before"])
    data["full_page"]["after"]["text_nodes"][0]["text"] = "Changed"
    record = wc.store_capture_record(tmp_path, VIEW, data)
    entry = record["full_page"]["text_artifact"]
    text = json.loads((tmp_path / entry["file"]).read_text())
    text["bracket"]["material"] = []
    raw = json.dumps(text).encode()
    (tmp_path / entry["file"]).write_bytes(raw)
    entry.update(sha256=wc.digest(raw), bytes=len(raw))
    with pytest.raises(ValueError):
        wc.verify_view(tmp_path, record, VIEW, wc.request_config("https://example.com/", views=[VIEW]))


@pytest.mark.parametrize("title,words", [("Hang Tight! Routing to checkout...", "Our store"),
                                         ("Store", "Sit tight. This page will automatically refresh.")])
def test_queue_page_is_not_usable(tmp_path, title, words):
    data = source()
    for key in ("first_screen", "full_page"):
        data[key]["before"]["title"] = title
        data[key]["before"]["text_nodes"][0]["text"] = words
    record = wc.store_capture_record(tmp_path, VIEW, data)
    result = wc.verify_view(tmp_path, record, VIEW, wc.request_config("https://example.com/", views=[VIEW]))
    assert result["status"] == "not usable" and result["views"]["first_screen"]["status"] == "not usable"


def test_horizontal_overflow_is_a_note_and_marks_text(tmp_path):
    data = source()
    data["horizontal_overflow"] = {"scroll_width": 60, "viewport_width": 24, "overflow_px": 36}
    data["full_page"]["before"]["text_nodes"][0]["bbox"] = [1, 1, 50, 12]
    record = wc.store_capture_record(tmp_path, VIEW, data)
    result = wc.verify_view(tmp_path, record, VIEW, wc.request_config("https://example.com/", views=[VIEW]))
    assert result["status"] == "usable" and result["horizontal_overflow"]["overflow_px"] == 36
    assert any("wider than the viewport" in n for n in result["views"]["full_page"]["notes"])
    text = json.loads((tmp_path / result["views"]["full_page"]["text"]["file"]).read_text())
    assert text["text_nodes"][0]["past_right_edge"] and text["text_nodes"][0]["in_column"]


def test_workflow_is_three_script_stages():
    workflow = yaml.safe_load((ROOT / "configs/design/workflows/design_web_capture.yaml").read_text())["workflow"]
    assert [node["name"] for node in workflow["nodes"]] == ["preflight", "capture", "verify"]
    for node in workflow["nodes"]:
        agent = yaml.safe_load((ROOT / f'configs/design/agents/{node["agent"]}.yaml').read_text())["agent"]
        assert agent["type"] == "script"
        assert "model" not in agent


def test_three_stages_independently_and_bound_receipts(tmp_path):
    class Client:
        def __init__(self, _url):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def call(self, code):
            if "return await captureWithBrowser" in code:
                return source()
            return {"isolated_context": True, "png": True, "context_closed": True}

    request = wc.request_config("https://example.com/", views=[VIEW])
    pre_path, pre = wc.asyncio.run(wc.preflight(tmp_path, request, Client))
    assert pre["status"] == "passed"
    cap_path, cap = wc.asyncio.run(wc.capture(tmp_path, pre_path, Client))
    assert cap["status"] == "completed"
    _, report = wc.verify(tmp_path, cap_path)
    assert report["verified"] and report["captures"][0]["status"] == "usable"
    with pytest.raises(ValueError, match="already recorded"):
        wc.verify(tmp_path, cap_path)


def test_preflight_failure_never_starts_capture(tmp_path):
    class Client:
        def __init__(self, _url):
            pass

        async def __aenter__(self):
            raise RuntimeError("Unavailable existing browser; no replacement")

        async def __aexit__(self, *_args):
            pass

    request = wc.request_config("https://example.com/", views=[VIEW])
    pre_path, pre = wc.asyncio.run(wc.preflight(tmp_path, request, Client))
    assert pre["status"] == "failed"
    with pytest.raises(ValueError, match="diagnostic only"):
        wc.asyncio.run(wc.capture(tmp_path, pre_path, Client))


@pytest.mark.parametrize("phase", ["preflight", "capture", "verify"])
def test_native_script_wrappers_pass_values_not_env_names(tmp_path, phase):
    from unittest.mock import MagicMock

    from temper_ai.agent.script_agent import ScriptAgent
    from temper_ai.tools.bash import Bash
    from temper_ai.tools.executor import ToolExecutor

    printer = tmp_path / "argv.py"
    printer.write_text("import sys,json; print(json.dumps(sys.argv[1:]))")
    config = yaml.safe_load((ROOT / f"configs/design/agents/design_web_capture_{phase}.yaml").read_text())["agent"]
    config["script_template"] = config["script_template"].replace("/app/configs/design/bin/design_web_capture.py", str(printer))
    executor = ToolExecutor(workspace_root=str(tmp_path))
    executor.register_tools({"Bash": Bash(config={"workspace_root": str(tmp_path)})})
    context = MagicMock()
    context.run_id = "capture-argv-fixture"
    context.node_path = phase
    context.agent_name = config["name"]
    context.workspace_path = str(tmp_path)
    context.skip_policies = None
    context.parent_event_id = None
    context.tool_executor = executor
    inputs = {"workspace_path": str(tmp_path), "url": "https://example.com/", "ready_selector": "body",
              "viewports": [VIEW], "timeout_ms": 30000, "browser_url": wc.BROWSER,
              "preflight_receipt": "preflight.json", "capture_receipt": "capture.json"}
    result = ScriptAgent(config=config).run(inputs, context)
    assert result.status.value == "completed"
    args = json.loads(result.output)
    assert args[0] == phase and str(tmp_path) in args
    assert not any(arg.startswith("TEMPER_V") for arg in args)
    if phase == "preflight":
        assert args[args.index("--timeout-ms") + 1] == "30000"
        assert json.loads(args[args.index("--viewports") + 1]) == [VIEW]
    else:
        assert args[args.index("--receipt") + 1] == inputs["preflight_receipt" if phase == "capture" else "capture_receipt"]


def test_browser_client_waits_past_five_minutes_but_records_a_call_that_never_answers(monkeypatch):
    """#150 R14: the MCP default 300 s stream read timeout left a 407 s capture call waiting forever."""
    import asyncio
    from contextlib import asynccontextmanager

    import mcp.client.streamable_http as transport
    stage = yaml.safe_load((ROOT / "configs/design/agents/design_web_capture_capture.yaml").read_text())
    stage_timeout = stage["agent"]["timeout_seconds"]
    seen = {}

    @asynccontextmanager
    async def fake_transport(url, *, http_client=None, terminate_on_close=True):
        seen["read"] = http_client.timeout.read
        raise RuntimeError("stop after transport setup")
        yield  # pragma: no cover

    monkeypatch.setattr(transport, "streamable_http_client", fake_transport)
    with pytest.raises(RuntimeError, match="stop after transport setup"):
        asyncio.run(wc.BrowserClient("http://127.0.0.1:1/mcp").__aenter__())
    assert seen["read"] > stage_timeout > wc.BrowserClient.CALL_DEADLINE_S > 300

    class Silent:
        async def call_tool(self, name, arguments):
            await asyncio.sleep(60)

    client = wc.BrowserClient("http://127.0.0.1:1/mcp", deadline_s=0.05)
    client.session = Silent()
    with pytest.raises(RuntimeError, match="browser call gave no answer within 0.05 s"):
        asyncio.run(client.call("async () => 1"))


def test_source_cannot_accept_cookies_or_mutate_shared_tab():
    js = (ROOT / "configs/design/bin/design_web_capture.js").read_text()
    assert "browser.newContext(" in js and "bypassCSP: false" in js
    assert "addStyleTag" not in js and "setBypassCSP" not in js
    assert "fullPage: true, animations: 'disabled', caret: 'hide', scale: 'css'" in js
    assert "viewport.height * 25" in js
    assert "only necessary" in js and "UNSAFE_CONSENT_CONTROL" in js
