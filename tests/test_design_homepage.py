"""Model-free contracts for Design's template-driven Penpot workflow.

No model payloads, accounts, browsers or services. Actual deployment, gates, API
persistence and exports are separate evidence in Design's pilot packet.
"""
import copy
import importlib.util
import json
import struct
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from temper_ai.stage.models import WorkflowConfig

BIN = Path(__file__).resolve().parents[1] / "configs/design/bin"
sys.path.insert(0, str(BIN))
spec = importlib.util.spec_from_file_location("design_homepage_v1", BIN / "design_homepage_v1.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


def reservation():
    return {"pacific_day": datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat(),
            "reserve_usd": 2.6, "day_spent_usd": 6.053515, "trial_spent_usd": 0,
            "trial_envelope_usd": 8.75, "subscription_checked": True, "one_design_experiment": True}


@pytest.mark.parametrize("workflow", ["design_homepage_v1", "design_homepage_pilot_v1"])
def test_schema_and_bounded_loop(workflow):
    path = BIN.parent / "workflows" / f"{workflow}.yaml"
    raw = yaml.safe_load(path.read_text())["workflow"]
    config = WorkflowConfig.from_dict(raw)
    assert config.name == workflow
    nodes = {n["name"]: n for n in raw["nodes"]}
    assert nodes["disposition"]["max_loops"] == 3
    assert nodes["disposition"]["loop_to"] == "design"
    assert nodes["budget"]["gate"] is True
    assert nodes["disposition"]["gate"] is True
    assert nodes["critic_a"]["agent"] == nodes["critic_b"]["agent"] == "design_critic"
    assert nodes["merge"]["agent"] == "design_merge"
    if workflow == "design_homepage_v1":
        assert nodes["direction"]["gate"] and nodes["final"]["gate"]
    else:
        assert not nodes["direction"].get("gate")
        assert "final" not in nodes
        assert nodes["brief"]["input_map"]["mode"] == "pilot"


@pytest.mark.parametrize("direction", h.DIRECTIONS)
@pytest.mark.parametrize("width", h.WIDTHS)
def test_editable_geometry_and_measurement(direction, width):
    canvas = h.Canvas(h.p.nid(), h.p.nid())
    canvas.homepage(copy.deepcopy(h.DEFAULT), direction, width)
    state = canvas.state({"team-id": h.p.nid()})
    facts = h.measure(state)
    assert facts["objects"]
    assert not facts["violations"]
    assert not facts["text_box_overlaps"]
    texts = [o for o in state["objects"] if o["type"] == "text"]
    assert len(texts) > 25
    assert all(o["content"]["children"] for o in texts)
    assert all("position-data" not in o for o in texts)
    assert state["components"]
    assert any(o.get("shape-ref") for o in state["objects"])
    assert set(h.RUNTIME_ONLY) <= set(facts["runtime_not_checked"])
    assert not any(o["type"] == "image" for o in state["objects"])


def test_structures_are_distinct():
    orders = []
    for direction in h.DIRECTIONS:
        canvas = h.Canvas(h.p.nid(), h.p.nid(), True)
        canvas.homepage(copy.deepcopy(h.DEFAULT), direction, 390)
        names = [m["name"] for m in canvas.metrics if m["board"].startswith("Wireframe ")]
        orders.append([name for name in names if name in ("H2 — How it works", "H2 — room examples", "Needs heading")])
    assert len({tuple(order) for order in orders}) == 3


@pytest.mark.parametrize("width", h.WIDTHS)
def test_review_r02_navigation_terms_and_named_room_facts(width):
    brief = {**h.DEFAULT, "terms": "Minimum booking: 1 hour\nCancellation: 24 hours ahead\nIllustrative terms for all rooms; check real venue terms before booking."}
    canvas = h.Canvas(h.p.nid(), h.p.nid())
    canvas.homepage(brief, "task-led", width)
    state = canvas.state({"team-id": h.p.nid()})
    metrics = [m for m in state["metrics"] if m["board"].startswith("Homepage ")]
    assert len([m for m in metrics if m["kind"] == "target" and "anchor" in m["name"]]) == 2
    terms = next(m for m in metrics if m["name"] == "H2 — example terms")
    assert terms["size"] == 28
    assert len([m for m in metrics if m["name"] == "Example term"]) == 2
    assert all(m["text"].startswith("Capacity: ") for m in metrics if m["name"] == "Capacity")
    assert all(m["text"].startswith("Equipment: ") for m in metrics if m["name"] == "Equipment")
    assert all(m["fg"] == h.PALETTE["ink"] for m in metrics if m["name"] == "Illustrative price")
    facts = h.measure(state)
    assert not facts["violations"] and not facts["text_box_overlaps"]


def test_original_schematics_show_the_three_capacities_without_fake_action_tiles():
    canvas = h.Canvas(h.p.nid(), h.p.nid())
    board = canvas.board("Schematic proof", 0, 0, 500, 300)
    for i, seats in enumerate((4, 8, 12)):
        before = len(canvas.objects)
        canvas.schematic(board, i * 150, 20, 120, 76, seats)
        added = canvas.objects[before:]
        assert len([o for o in added if o["name"] == "Illustrative seat"]) == seats
        perimeter = next(o for o in added if o["name"] == "Illustrative room perimeter")
        assert perimeter["fills"][0]["fill-color"] == h.PALETTE["paper"]
        assert perimeter["strokes"][0]["stroke-alignment"] == "outer"


def test_tablet_steps_are_stacked_for_readable_explanation():
    canvas = h.Canvas(h.p.nid(), h.p.nid())
    canvas.homepage(copy.deepcopy(h.DEFAULT), "task-led", 768)
    steps = [m for m in canvas.metrics if m["board"].startswith("Homepage ") and m["name"] == "Step title"]
    assert len({m["x"] for m in steps}) == 1
    assert len({m["y"] for m in steps}) == 3


def test_real_cannot_use_pilot_or_provisional_approval():
    brief = {**h.DEFAULT, "fictional": False}
    with pytest.raises(ValueError, match="refuses real"):
        h.direction_contract(brief, {"direction": "task-led"}, True)
    with pytest.raises(ValueError, match="owner direction"):
        h.direction_contract(brief, {"direction": "task-led", "approval": "provisional-fictional"}, False)
    result = h.direction_contract(brief, {"direction": "task-led", "approval": "owner-direction"}, False)
    assert result["owner_taste_approved"] is False


def test_fictional_choice_never_claims_owner_approval():
    result = h.direction_contract(h.DEFAULT, {"direction": "task-led", "approval": "owner-direction"}, True)
    assert result["approval"] == "provisional-fictional"
    assert not result["owner_taste_approved"]


def test_bad_copy_and_missing_brief():
    with pytest.raises(ValueError, match="explicit fictional"):
        h.brief_contract({})
    with pytest.raises(ValueError, match="exceeds"):
        h.brief_contract({**h.DEFAULT, "headline": "A" * 86})
    with pytest.raises(ValueError, match="disclose demo"):
        h.brief_contract({**h.DEFAULT, "cta": "Book now"})


@pytest.mark.parametrize("changes, error", [
    ({"reserve_usd": 4}, "Pacific-day"),
    ({"trial_spent_usd": 7}, "envelope"),
    ({"trial_envelope_usd": 11}, "envelope"),
    ({"pacific_day": "2000-01-01"}, "expired"),
    ({"subscription_checked": False}, "subscription"),
    ({"reserve_usd": float("nan")}, "finite"),
])
def test_budget_guard_errors(changes, error):
    with pytest.raises(ValueError, match=error):
        h.budget_contract({**reservation(), **changes}, 1)


def test_budget_round_ceiling():
    assert h.budget_contract(reservation(), 3)
    with pytest.raises(ValueError, match="maximum three"):
        h.budget_contract(reservation(), 4)


def test_resume_reuses_and_refuses_changed_completed_stage(tmp_path):
    job = h.Job(tmp_path)
    first = job.brief(json.dumps(h.DEFAULT), True)
    checkpoint = h.load(job.state_path)
    second = h.Job(tmp_path).brief(json.dumps(h.DEFAULT), True)
    assert second["reused"] and first["status"] == "completed"
    assert h.load(job.state_path) == checkpoint
    with pytest.raises(ValueError, match="inputs changed"):
        h.Job(tmp_path).brief(json.dumps({**h.DEFAULT, "subhead": "Different message."}), True)


def test_unknown_and_nonjson_direction_errors():
    with pytest.raises(ValueError, match="JSON decision"):
        h.safe_gate("yes please")
    with pytest.raises(ValueError, match="direction must"):
        h.direction_contract(h.DEFAULT, {"direction": "recolour"}, True)


def test_no_canvas_fallback_or_credential_in_output(monkeypatch):
    monkeypatch.setenv("PENPOT_URL", "https://spark.tailbb5055.ts.net:8790")
    monkeypatch.setenv("PENPOT_AGENT_EMAIL", "design-agent@spark.local")
    monkeypatch.delenv("PENPOT_AGENT_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="never substitute"):
        h.Penpot().login()
    monkeypatch.setenv("PENPOT_URL", "https://untrusted.example")
    with pytest.raises(ValueError, match="authorized Penpot host"):
        h.Penpot()


def test_container_bootstrap_only_reads_explicitly_authorized_login(monkeypatch):
    box = "temper-run-89bcec85-9acc-4094-b4ab-5bc5eb7fac17"
    monkeypatch.delenv("PENPOT_AGENT_PASSWORD", raising=False)
    monkeypatch.setenv("TEMPER_RUN_CONTAINER", box)
    data = (f"TEMPER_RUN_CONTAINER={box}\0PENPOT_AGENT_EMAIL=design-agent@spark.local\0"
            "PENPOT_AGENT_PASSWORD=fictional-test-value\0OTHER_PASSWORD=never-return\0").encode()
    reads = []
    def read(path):
        reads.append(str(path))
        return data
    monkeypatch.setattr(h.Path, "read_bytes", read)
    assert h.Penpot.password() == "fictional-test-value"
    assert reads == ["/proc/1/environ"]


@pytest.mark.parametrize("box", ["", "temper-ai-worker-1", "temper-run-not-a-uuid"])
def test_no_bootstrap_read_outside_own_run_container(monkeypatch, box):
    monkeypatch.delenv("PENPOT_AGENT_PASSWORD", raising=False)
    monkeypatch.setenv("TEMPER_RUN_CONTAINER", box)
    def forbidden(path):
        pytest.fail("must never read host or worker environment")
    monkeypatch.setattr(h.Path, "read_bytes", forbidden)
    assert h.Penpot.password() == ""


@pytest.mark.parametrize("changed", ["other-container", "other-profile", "unreadable"])
def test_bootstrap_identity_mismatch_fails_closed(monkeypatch, changed):
    box = "temper-run-89bcec85-9acc-4094-b4ab-5bc5eb7fac17"
    monkeypatch.delenv("PENPOT_AGENT_PASSWORD", raising=False)
    monkeypatch.setenv("TEMPER_RUN_CONTAINER", box)
    def read(path):
        if changed == "unreadable":
            raise PermissionError("test fixture")
        identity = "temper-run-00000000-0000-0000-0000-000000000000" if changed == "other-container" else box
        email = "someone-else@example.invalid" if changed == "other-profile" else "design-agent@spark.local"
        return f"TEMPER_RUN_CONTAINER={identity}\0PENPOT_AGENT_EMAIL={email}\0PENPOT_AGENT_PASSWORD=fixture\0".encode()
    monkeypatch.setattr(h.Path, "read_bytes", read)
    assert h.Penpot.password() == ""


def test_drafts_identity_is_discovered_not_guessed(monkeypatch):
    monkeypatch.setenv("PENPOT_URL", "https://spark.tailbb5055.ts.net:8790")
    monkeypatch.setenv("PENPOT_AGENT_EMAIL", "design-agent@spark.local")
    monkeypatch.setenv("PENPOT_AGENT_PASSWORD", "fictional-test-value")
    client = h.Penpot()
    calls = []
    def rpc(method, args=None):
        calls.append((method, args))
        if method == "login-with-password":
            return {"email": "design-agent@spark.local"}
        if method == "get-profile":
            return {"email": "design-agent@spark.local", "default-project-id": "own-drafts", "default-team-id": "own-team"}
        if method == "create-file":
            return {"id": "new-file"}
        return {"id": "new-file", "project-id": "own-drafts", "team-id": "own-team"}
    monkeypatch.setattr(client, "rpc", rpc)
    client.login()
    client.create("Fictional test only")
    assert ("create-file", {"name": "Fictional test only", "project-id": "own-drafts"}) in calls
    assert "PROJECT" not in vars(h)


def test_file_outside_own_drafts_is_refused(monkeypatch):
    monkeypatch.setenv("PENPOT_URL", "https://spark.tailbb5055.ts.net:8790")
    client = h.Penpot()
    client.project = "own-drafts"
    client.profile = {"default-team-id": "own-team"}
    monkeypatch.setattr(client, "rpc", lambda *args: {"project-id": "owner-project", "team-id": "different-team"})
    with pytest.raises(ValueError, match="outside design-agent"):
        client.get("file")


def tiny_font(fmt):
    """Two-glyph Unicode font, not a copied licensed asset or third-party service."""
    head, hhea = bytearray(20), bytearray(36)
    struct.pack_into(">H", head, 18, 1000)
    struct.pack_into(">H", hhea, 34, 3)
    if fmt == 4:
        sub = struct.pack(">7H", 4, 32, 0, 4, 4, 1, 0)
        sub += struct.pack(">9H", 66, 65535, 0, 65, 65535, 65472, 65535, 0, 0)
    else:
        sub = struct.pack(">HHIII3I", 12, 0, 28, 0, 1, 65, 66, 1)
    cmap = struct.pack(">HHHHI", 0, 1, 3, 1 if fmt == 4 else 10, 12) + sub
    tables = {b"head": bytes(head), b"hhea": bytes(hhea),
              b"hmtx": struct.pack(">6H", 500, 0, 600, 0, 600, 0), b"cmap": cmap}
    offset = 12 + 16 * len(tables)
    directory, body = b"", b""
    for name, data in tables.items():
        directory += struct.pack(">4sIII", name, 0, offset, len(data))
        body += data
        offset += len(data)
    return struct.pack(">I4H", 65536, len(tables), 0, 0, 0) + directory + body


@pytest.mark.parametrize("fmt", [4, 12])
def test_native_text_cache_uses_font_advances(fmt):
    font = h.p.FontMetrics(tiny_font(fmt))
    assert font.width("AB", 20) == 24
    with pytest.raises(ValueError, match="lacks U"):
        font.width("Z", 20)
    with pytest.raises(ValueError, match="Latin/LTR"):
        font.width("界", 20)
    style, ink, fid = h.p.typography("Fixture", 20, "600"), h.p.color("Ink", "#111111"), h.p.nid()
    obj = {"x": 14, "y": 18, "width": 100, "content": h.p.content(["AB"], style, ink, fid, "center")}
    positions = h.p.text_positions(obj, {"600": font})
    assert positions[0]["x"] == 52
    assert positions[0]["width"] == 24
    assert positions[0]["text"] == "AB"
    assert positions[0]["fills"][0]["fill-color-ref-file"] == fid


def test_component_instance_translates_native_text_cache():
    class Metric:
        def width(self, text, size):
            return len(text) * size * .4
    canvas = h.Canvas(h.p.nid(), h.p.nid())
    canvas.fonts = {"400": Metric(), "600": Metric()}
    component = canvas.button("Explore demo rooms")
    board = canvas.board("Fixture", 0, 0, 390, 300)
    canvas.instance(component, board, 24, 48, action=True)
    main = next(o for o in component["objects"] if o["type"] == "text")
    instance = next(o for o in canvas.objects if o.get("shape-ref") == main["id"])
    assert instance["position-data"][0]["x"] - main["position-data"][0]["x"] == 24 - component["objects"][0]["x"]
    assert instance["position-data"][0]["y"] - main["position-data"][0]["y"] == 48 - component["objects"][0]["y"]
    assert instance["position-data"][0]["x1"] == main["position-data"][0]["x1"]
    assert not h.measure(canvas.state({"team-id": h.p.nid()}))["violations"]


def test_source_sans_pro_uses_verified_penpot_variant():
    t = h.p.typography("Fixture", 20, "600")
    assert t["font-variant-id"] == "600"
    assert t["font-family"] == "sourcesanspro"
    c = h.p.content(["Fixture"], t, h.p.color("Ink", "#111111"), h.p.nid())
    assert c["vertical-align"] == "top"
    paragraph = c["children"][0]["children"][0]
    assert paragraph["text-direction"] == "ltr"
    assert "direction" not in paragraph


def test_completion_not_self_attested(tmp_path):
    job = h.Job(tmp_path)
    assert not job.state["packet_verified"]
    assert not job.state["owner_taste_approved"]
    with pytest.raises(ValueError, match="final owner gate"):
        job.final("{}")


def test_unreferenced_or_fourth_fix_refused(tmp_path):
    job = h.Job(tmp_path)
    (tmp_path / "review").mkdir()
    h.save(tmp_path / "review/findings.json", {"findings": [{"id": "D1"}]})
    job.state["review_round"] = 1
    with pytest.raises(ValueError, match="existing evidence"):
        job.disposition(json.dumps({"action": "fix", "issues": ["made-up"], "patch": {"subhead": "Shorter."}}))
    job.state["review_round"] = 3
    with pytest.raises(ValueError, match="exhausted"):
        job.disposition(json.dumps({"action": "fix", "issues": ["D1"], "patch": {"subhead": "Shorter."}}))


def test_all_button_states_use_penpot_stroke_enum():
    canvas = h.Canvas(h.p.nid(), h.p.nid())
    for state in ("default", "hover", "focus", "pressed", "disabled", "loading"):
        canvas.button("Explore demo rooms", state)
    strokes = [s for obj in canvas.objects for s in obj.get("strokes", [])]
    assert strokes
    assert all(s["stroke-alignment"] in {"inner", "center", "outer"} for s in strokes)
    focus = next(o for o in canvas.objects if o["name"] == "Primary / focus")
    assert focus["strokes"][0]["stroke-alignment"] == "outer"
    assert focus["strokes"][0]["stroke-width"] == 3


def empty_pending(tmp_path):
    fid, page = h.p.nid(), h.p.nid()
    path = tmp_path / "source.pending.json"
    h.save(path, {"file_id": fid, "page_id": page})
    file = {"id": fid, "name": "Known pending source", "revn": 0,
            "data": {"pages-index": {page: {"objects": {h.p.ROOT: {}}}}}}
    class Client:
        def get(self, requested):
            assert requested == fid
            return file
        def create(self, *args):
            pytest.fail("recovery must never create another file")
    return Client(), path, file


def test_recover_only_recorded_empty_draft(tmp_path):
    client, path, file = empty_pending(tmp_path)
    assert h.recover_empty_pending(client, path, "Known pending source") is file
    assert h.load(path)["file_id"] == file["id"]


@pytest.mark.parametrize("changed", ["revision", "object", "name", "page", "library"])
def test_pending_recovery_refuses_ambiguous_or_wrong_source(tmp_path, changed):
    client, path, file = empty_pending(tmp_path)
    page = next(iter(file["data"]["pages-index"].values()))
    if changed == "revision":
        file["revn"] = 1
    elif changed == "object":
        page["objects"][h.p.nid()] = {"type": "text"}
    elif changed == "name":
        file["name"] = "Different source"
    elif changed == "page":
        file["data"]["pages-index"][h.p.nid()] = {"objects": {}}
    else:
        file["data"]["colors"] = {h.p.nid(): {"name": "Already saved"}}
    with pytest.raises(ValueError, match="never duplicate or overwrite"):
        h.recover_empty_pending(client, path, "Known pending source")
