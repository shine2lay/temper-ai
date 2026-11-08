"""design_app_screen_v1 step 4, reuse (Design #214, updated in #233): commit + spec_sha256 fingerprint,
per-screen visual diff when the commit moves, the product store, prepare's reuse and delta, the stage steps over
a stored copy, ground's delta merge, and the tool registry.

The app, screens and words are invented test data (the repository is public). Browser capture and /api/health
are replaced at the boundary by stubs that return known commits and PNGs, never a mode inside the code (rule 42).
"""
from __future__ import annotations

import copy
import importlib.util
import json
import struct
import sys
import zlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "configs/design/bin"
sys.path.insert(0, str(BIN))

from app_screen import (  # noqa: E402
    contracts,
    existing,
    existing_host,
    ground_delta,
    ground_task,
    product_app,
    reuse,
    reuse_host,
    stored_copy,
    tools_registry,
)
from app_screen.product_store import ProductStore, StoreError  # noqa: E402
from app_screen.workspace import Workspace  # noqa: E402


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def _make_png(rgb: tuple[int, int, int]) -> bytes:
    w, h = 4, 4
    row = b"\x00" + bytes(rgb) * w
    raw = row * h
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )


PNG = _make_png((20, 40, 80))
NEW_PNG = _make_png((220, 60, 30))


def _raw(w: int, h: int, runs: list[str], errors: list | None = None) -> dict:
    return {"viewport": {"w": w, "h": h}, "pageHeight": h, "screensTall": 1,
            "chrome": {"tabbar": 60, "tabbarRows": 1, "contentLeftInFirstView": h - 60},
            "type": {"total": 10, "under12": 0, "under16": 0, "bodyLikeRuns": 2, "bodyLikeUnder16": 0,
                     "distinctSizes": 3, "smallestPx": 14},
            "targets": {"under24NotInline": 0}, "overflow": {"sideScrollers": []},
            "truncated": {"count": 0, "items": []}, "blocks": {"alwaysOpen": 2}, "errors": errors or [],
            "pageErrors": [], "keyRegions": {"main_status": {"top": 100}},
            "runs": [{"text": t, "first": True} for t in runs]}


RAW = {
    "home-390-normal": _raw(390, 844, ["Water today", "Fern needs water by noon"]),
    "list-390-normal": _raw(390, 844, ["Plants", "Fern", "Basil"]),
    "list-390-error": _raw(390, 844, ["Could not load plants"], [{"text": "Could not load plants", "actions": []}]),
}
REQUIREMENTS = {"source": "test", "items": [
    {"id": "R1", "item": "S1", "owner_words": "show what needs water first", "kind": "goal",
     "means": "The plants to water today come first.", "maps_to": ["home"]}]}
JOURNEYS = {
    "journeys": [{"id": "J1", "name": "See what needs water", "goal": "Know which plant to water today",
                  "screens": ["home"], "problems": [], "requirements": ["R1"],
                  "keep": [{"what": "The home names the plant and the time",
                            "evidence": [{"capture": "home-390-normal", "text": "Fern needs water by noon"}]}]},
                 {"id": "J2", "name": "Browse the plants", "goal": "Find one plant", "screens": ["list"],
                  "problems": ["P1"], "keep": []}],
    "problems": [{"id": "P1", "claim": "The error says it failed but offers nothing to do.", "severity": 3,
                  "kind": "error-recovery",
                  "evidence": [{"capture": "list-390-error", "measure": "error_messages_without_action",
                                "value": 1}, {"capture": "list-390-error", "text": "Could not load plants"}]}]}


def _app_file() -> dict:
    return {
        "product": "demo", "name": "Demo", "job": "Demo shows a gardener which plants need water today.",
        "page": {"main": "main", "key_regions": {"main_status": "#status"}, "error_selector": "[role=alert]"},
        "sizes": {"390": {"height": 844, "phone": True}},
        "sheet_width": 390,
        "screens": [
            {"id": "home", "name": "Home", "route": "/index.html", "widths": [390],
             "states": {"normal": {"what": "today's plants"}}},
            {"id": "list", "name": "Plants", "route": "/list.html", "widths": [390],
             "states": {"normal": {}, "error": {"query": "?state=error", "what": "the list fails to load"}}},
        ],
    }


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")


def _sheet(caps, out):
    out.write_bytes(PNG)
    return {"file": out.name, "bytes": len(PNG), "width": 1, "height": 1, "tiles": [c for c, _ in caps]}


CAPTURED_AT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


class StoppedClock:
    """existing_host's datetime, stopped so two captures of the same state write identical bytes."""

    @staticmethod
    def now(tz=None):
        assert tz is UTC, f"the stopped clock stands in for datetime.now(UTC) only, got {tz!r}"
        return CAPTURED_AT


@pytest.fixture()
def lab(tmp_path: Path, monkeypatch) -> dict:
    """A product repo with .temper/design/app.yaml, a store dir, and boundary stubs for /api/health and shoot."""
    repo_dir = tmp_path / "demo-repo"
    _write(repo_dir / ".temper" / "design" / "app.yaml", yaml.safe_dump(_app_file(), sort_keys=False))
    products = tmp_path / "products"
    state = {
        "commit": "1111111a",
        "version": "0.1.0",
        "changed_screens": set(),
    }
    shot: list[list[str]] = []

    def fake_health(url: str, timeout: float = 15.0):
        return 200, json.dumps({"ok": True, "version": state["version"], "commit": state["commit"]})

    def shoot(instance, caps, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        shot.append([c["id"] for c in caps])
        raw = {}
        for c in caps:
            changed = c["screen"] in state["changed_screens"]
            (out_dir / f"{c['id']}.png").write_bytes(NEW_PNG if changed else PNG)
            raw[c["id"]] = copy.deepcopy(RAW[c["id"]])
            if changed:
                raw[c["id"]]["runs"].append({"text": "No plants saved yet", "first": True})
        _write(out_dir / existing_host.RAW, raw)
        return raw, {}

    monkeypatch.setattr(existing_host, "datetime", StoppedClock)
    monkeypatch.setattr(existing_host, "shoot", shoot)
    monkeypatch.setattr(existing_host.existing_sheet, "build", _sheet)
    monkeypatch.setattr(reuse_host.ground_host, "prep",
                        lambda product_or_repo, workspace, store=None: {"product": "demo"})
    return {
        "repo": repo_dir,
        "products": products,
        "shot": shot,
        "state": state,
        "health_opener": fake_health,
        "base_url": "http://127.0.0.1:18100",
        "tmp": tmp_path,
    }


def _finished_existing(lab: dict, name: str = "ws-full") -> Workspace:
    """A workspace whose stage 2 finished and passed at commit 1111111a."""
    app = product_app.load(lab["repo"])
    app["commit"] = lab["state"]["commit"]
    app["version"] = lab["state"]["version"]
    app["base_url"] = lab["base_url"]
    (lab["tmp"] / name).mkdir()
    w = Workspace(lab["tmp"] / name)
    w.start("demo")
    folder = w.folder("existing")
    caps = product_app.captures(app)
    (folder / existing_host.CAPTURES).mkdir(parents=True)
    for c in caps:
        (folder / existing_host.CAPTURES / f"{c['id']}.png").write_bytes(PNG)
    _write(folder / existing_host.RAW, RAW)
    _write(folder / existing_host.RECORD, {
        "captures": len(caps), "failed": {},
        "base_url": lab["base_url"], "commit": app["commit"], "version": app["version"],
        "spec_sha256": app["spec_sha256"],
        "accounts": {c["id"]: c.get("account") for c in caps},
    })
    existing_host.write_outputs(app, caps, RAW, folder)
    _write(w.folder("intake") / "requirements.json", REQUIREMENTS)
    existing.collect(w, "")
    assert existing.check(w, json.dumps(JOURNEYS))["verdict"] == "ok"
    existing.run(w, "")
    w.mark("existing", "done")
    return w


def _stored(lab: dict) -> ProductStore:
    w = _finished_existing(lab)
    out = reuse_host.store(str(w.path), "run-1", "existing", "abc123", lab["products"])
    assert out["stored"] == {"existing": {"version": 1, "new": True}}
    return ProductStore("demo", lab["products"])


def _fresh(lab: dict, name: str) -> Path:
    path = lab["tmp"] / name
    path.mkdir()
    _write(path / "01-request" / "requirements.json", REQUIREMENTS)
    return path


# --- fingerprint and decision (commit + spec_sha256 + per-screen visual diff) ---------------------------------

def _spec_app(**change) -> dict:
    app = {**_app_file(), "spec_sha256": "aaa111"}
    return {**app, **change}


def _stored_source(commit: str = "1111111a") -> dict:
    app = _spec_app()
    return {"version": 1, "run": "run-1", "fingerprint": reuse.fingerprint(app, commit=commit)}


def test_same_commit_and_same_spec_is_reused():
    app = _spec_app()
    fp = reuse.fingerprint(app, commit="1111111a")
    d = reuse.decide_existing(app, fp, _stored_source("1111111a"), [], False)
    assert d.decision == "reuse" and "unchanged since v1" in d.reason


def test_moved_commit_with_same_spec_defers_to_per_screen_visual_diff():
    app = _spec_app()
    fp = reuse.fingerprint(app, commit="2222222b")
    d = reuse.decide_existing(app, fp, _stored_source("1111111a"), [], False)
    assert d.decision == "pending"
    assert "commit moved from 1111111a to 2222222b" in d.reason


def test_visual_diff_reuses_identical_screens_and_marks_changed_screens(tmp_path):
    app = _spec_app()
    caps = product_app.captures(app)
    stored_dir = tmp_path / "stored"
    cand_same = tmp_path / "cand_same"
    cand_diff = tmp_path / "cand_diff"
    for d in (stored_dir, cand_same, cand_diff):
        (d / "captures").mkdir(parents=True)
    for c in caps:
        (stored_dir / "captures" / f"{c['id']}.png").write_bytes(PNG)
        (cand_same / "captures" / f"{c['id']}.png").write_bytes(PNG)
        (cand_diff / "captures" / f"{c['id']}.png").write_bytes(NEW_PNG if c["screen"] == "list" else PNG)

    assert reuse.diff_screens_by_visual(app, stored_dir, cand_same) == ([], {})
    changed, ratios = reuse.diff_screens_by_visual(app, stored_dir, cand_diff)
    assert changed == ["list"]
    assert ratios["home-390-normal"] == 0.0 and ratios["list-390-normal"] > 0.0


@pytest.mark.parametrize("force, problems, change, words", [
    (True, (), {}, "forced"),
    (False, ("audit.json: changed since it was stored",), {}, "is invalid"),
    (False, (), {"screens": _app_file()["screens"][:1]}, "screens"),
    (False, (), {"sizes": {"390": {"height": 844}, "1440": {"height": 900}}}, "sizes"),
    (False, (), {"spec_sha256": "bbb222"}, "design spec"),
])
def test_run_in_full_when_forced_invalid_or_spec_changed(force, problems, change, words):
    app = _spec_app(**change)
    fp = reuse.fingerprint(app, commit="1111111a")
    d = reuse.decide_existing(app, fp, _stored_source("1111111a"), list(problems), force)
    assert d.decision == "run" and words in d.reason


def test_nothing_stored_runs_and_ground_follows_existing():
    app = _spec_app()
    fp = reuse.fingerprint(app, commit="1111111a")
    d = reuse.decide_existing(app, fp, None, [], False)
    assert d.decision == "run" and "nothing stored" in d.reason
    source = _stored_source("1111111a")
    assert reuse.decide_ground(d, source, [], False).decision == "run"
    reused = reuse.decide_existing(app, fp, source, [], False)
    assert reuse.decide_ground(reused, source, [], False).decision == "pending"
    delta = reuse.Decision("delta", "1 screen changed", screens=["list"])
    assert reuse.decide_ground(delta, source, [], False).decision == "pending"
    assert reuse.decide_ground(reused, source, [], True).decision == "run"
    assert reuse.decide_ground(reused, None, [], False).decision == "run"


def test_force_names_only_known_stages():
    assert reuse.parse_force("existing,ground") == {"existing", "ground"}
    with pytest.raises(reuse.ReuseError, match="--force takes"):
        reuse.parse_force("intake")


# --- product store --------------------------------------------------------------------------------------------

def test_store_keeps_a_passed_stage_and_it_validates(lab):
    ps = _stored(lab)
    assert ps.current() == {"existing": 1} and ps.validate("existing") == []
    source = ps.source("existing")
    assert source["run"] == "run-1" and source["workflow_commit"] == "abc123" and source["viewports"] == [390]
    assert source["commit"] == "1111111a"
    assert source["fingerprint"]["commit"] == "1111111a"
    assert len(source["fingerprint"]["spec_sha256"]) == 64
    assert source["request"]["items"] == [{"id": "R1", "owner_words": "show what needs water first"}]
    assert reuse_host.validate(lab["repo"], lab["products"]) == {"product": "demo", "valid": {"existing": 1}}
    history = ps.history()["requests"]
    assert history[-1]["run"] == "run-1" and history[-1]["stages"]["existing"]["version"] == 1


def test_store_refuses_a_failed_or_unchecked_stage(lab):
    w = _finished_existing(lab)
    w.mark("existing", "failed", reason="the final check found 2 problems")
    with pytest.raises(StoreError, match="existing: status 'failed'"):
        reuse_host.store(str(w.path), "run-2", "existing", None, lab["products"])
    w.mark("existing", "done")
    _write(w.folder("existing") / "check-final.json", {"verdict": "retry", "problems": [
        {"check": "evidence", "where": "P1", "problem": "no such capture"}], "counts": {}})
    with pytest.raises(StoreError, match="only a passed stage is stored"):
        reuse_host.store(str(w.path), "run-2", "existing", None, lab["products"])
    assert not (lab["products"] / "demo" / "store" / "current.json").exists()


def test_two_captures_of_the_same_app_write_the_same_bytes(lab):
    assert existing_host.datetime.now(UTC) == CAPTURED_AT
    first, second = _finished_existing(lab, "ws-clock-a"), _finished_existing(lab, "ws-clock-b")
    for name in ("audit.json", "journeys.json"):
        assert (first.folder("existing") / name).read_bytes() == (second.folder("existing") / name).read_bytes()
    assert CAPTURED_AT.isoformat(timespec="seconds") in json.loads(
        (first.folder("existing") / "audit.json").read_text())["source"]


def test_same_files_add_no_version_and_older_versions_stay(lab):
    ps = _stored(lab)
    w = _finished_existing(lab, "ws-again")
    assert reuse_host.store(str(w.path), "run-2", "existing", None, lab["products"])["stored"]["existing"] == \
        {"version": 1, "new": False}
    (w.folder("existing") / "captures" / "home-390-normal.png").write_bytes(NEW_PNG)
    assert reuse_host.store(str(w.path), "run-3", "existing", None, lab["products"])["stored"]["existing"] == \
        {"version": 2, "new": True}
    assert ps.versions("existing") == [1, 2] and ps.validate("existing", 1) == []
    assert len(ps.history()["requests"]) == 3


def test_a_changed_stored_file_makes_the_version_invalid(lab):
    ps = _stored(lab)
    (ps.version_dir("existing", 1) / "audit.json").write_text("{}", encoding="utf-8")
    problems = ps.validate("existing")
    assert any("audit.json: changed since it was stored" in p for p in problems)
    with pytest.raises(StoreError, match="existing v1"):
        reuse_host.validate(lab["repo"], lab["products"])


# --- prepare and the stage steps ------------------------------------------------------------------------------

def _files(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def _cli():
    spec = importlib.util.spec_from_file_location("design_app_screen_cli", BIN / "design_app_screen.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_same_commit_and_same_spec_reuses_stage_2_without_shooting_and_skips_the_model(lab):
    ps = _stored(lab)
    path = _fresh(lab, "ws-reuse")
    out = reuse_host.prepare(
        lab["repo"], str(path), None, lab["products"],
        base_url=lab["base_url"], health_opener=lab["health_opener"],
    )
    assert out["existing"]["decision"] == "reuse" and lab["shot"] == []
    w = Workspace(path)
    assert _files(w.folder("existing")) == {rel: (ps.version_dir("existing", 1) / rel).read_bytes()
                                            for rel in ps.source("existing")["files"]}
    run = w.run()["stages"]["existing"]
    assert run["status"] == "planned" and run["source_run"] == "run-1" and run["store_version"] == 1
    with pytest.raises(StoreError, match="status 'planned'"):
        reuse_host.store(str(path), "run-2", "existing", None, lab["products"])
    cli = _cli()
    results = [cli.run_step(step, str(path), "demo", "")
               for step in ("existing_collect", "existing_sheet", "existing_check", "existing")]
    assert [r.get("model") for r in results[:2]] == ["no", "no"] and results[2]["verdict"] == "ok"
    assert w.run()["stages"]["existing"]["status"] == "reused"
    assert w.run()["stages"]["existing"]["decision"] == "reuse"
    assert ps.validate("existing") == []


def test_commit_moved_but_screens_render_identically_reuses_every_screen(lab):
    ps = _stored(lab)
    lab["state"]["commit"] = "2222222b"
    lab["state"]["changed_screens"] = set()
    path = _fresh(lab, "ws-moved-identical")
    out = reuse_host.prepare(
        lab["repo"], str(path), None, lab["products"],
        base_url=lab["base_url"], health_opener=lab["health_opener"],
    )
    assert out["existing"]["decision"] == "reuse"
    assert "visually identical" in out["existing"]["reason"]
    w = Workspace(path)
    stored = ps.version_dir("existing", 1)
    assert (w.folder("existing") / "journeys.json").read_bytes() == (stored / "journeys.json").read_bytes()
    assert (w.folder("existing") / "captures/home-390-normal.png").read_bytes() == (stored / "captures/home-390-normal.png").read_bytes()


def test_commit_moved_and_one_screen_changed_recaptures_only_that_screen(lab):
    ps = _stored(lab)
    lab["state"]["commit"] = "3333333c"
    lab["state"]["changed_screens"] = {"list"}
    path = _fresh(lab, "ws-delta")
    out = reuse_host.prepare(
        lab["repo"], str(path), None, lab["products"],
        base_url=lab["base_url"], health_opener=lab["health_opener"],
    )
    assert out["existing"]["decision"] == "delta" and out["existing"]["screens"] == ["list"]
    folder, stored = Workspace(path).folder("existing"), ps.version_dir("existing", 1)
    assert (folder / "captures/home-390-normal.png").read_bytes() == (stored / "captures/home-390-normal.png").read_bytes()
    assert (folder / "captures/list-390-normal.png").read_bytes() == NEW_PNG
    audit = json.loads((folder / "audit.json").read_text())
    old = json.loads((stored / "audit.json").read_text())
    home = [s for s in audit["screens"] if s["screen"] == "home"]
    assert home == [s for s in old["screens"] if s["screen"] == "home"]
    texts = (folder / "texts.json").read_text()
    assert "No plants saved yet" in texts
    record = json.loads((folder / existing_host.RECORD).read_text())
    assert record["delta"] == ["list-390-normal", "list-390-error"]
    assert record["commit"] == "3333333c"
    assert Workspace(path).run()["stages"]["existing"]["status"] == "planned"
    assert Workspace(path).decision("existing")["screens"] == ["list"]


def test_a_reused_copy_that_changed_fails_loud(lab):
    _stored(lab)
    path = _fresh(lab, "ws-tampered")
    reuse_host.prepare(
        lab["repo"], str(path), None, lab["products"],
        base_url=lab["base_url"], health_opener=lab["health_opener"],
    )
    (path / "02-existing" / "journeys.json").write_text("{}", encoding="utf-8")
    with pytest.raises(stored_copy.StoredCopyError, match="journeys.json: changed since prepare"):
        existing.collect(Workspace(path), "")


def test_forced_run_captures_everything(lab):
    _stored(lab)
    path = _fresh(lab, "ws-forced")
    out = reuse_host.prepare(
        lab["repo"], str(path), "existing,ground", lab["products"],
        base_url=lab["base_url"], health_opener=lab["health_opener"],
    )
    assert out["existing"]["decision"] == "run" and out["ground"]["decision"] == "run"
    assert lab["shot"] == [["home-390-normal", "list-390-normal", "list-390-error"]]


def test_prepare_needs_a_fresh_workspace(lab):
    _stored(lab)
    path = _fresh(lab, "ws-used")
    _write(path / "02-existing" / "audit.json", {})
    with pytest.raises(StoreError, match="prepare needs a fresh workspace"):
        reuse_host.prepare(
            lab["repo"], str(path), None, lab["products"],
            base_url=lab["base_url"], health_opener=lab["health_opener"],
        )


# --- ground's delta -------------------------------------------------------------------------------------------

STORED_DRAFT = {
    "screens": [{"id": "home", "name": "Home", "sources": ["page:/", "screen:home", "req:R1"],
                 "states": [{"name": "loaded", "sources": ["screen:home"]},
                            {"name": "empty", "sources": ["req:R1"]}],
                 "shows": [{"what": "plants to water today", "sources": ["req:R1", "api:GET /api/plants"]}],
                 "actions": [{"id": "water", "what": "mark watered", "states": ["loaded"], "sources": ["page:/"]}]},
                {"id": "list", "name": "Plants", "sources": ["page:/list", "screen:list"],
                 "states": [{"name": "loaded", "sources": ["screen:list"]}]}],
    "excluded": [{"source": "api:GET /api/health", "reason": "a health check, nothing to show"}],
}
STORED_ITEMS = [{"id": "page:/", "kind": "page", "text": "Home"}, {"id": "page:/list", "kind": "page", "text": "List"},
                {"id": "screen:home", "kind": "screen", "text": "home"}, {"id": "screen:list", "kind": "screen",
                                                                        "text": "list"},
                {"id": "req:R1", "kind": "req", "text": "show what needs water first"},
                {"id": "api:GET /api/plants", "kind": "api", "text": "plants"},
                {"id": "api:GET /api/health", "kind": "api", "text": "health"},
                {"id": "seen:list", "kind": "seen", "text": "Plants | Fern | Basil"}]


def _fresh_items(**words) -> list[dict]:
    items = copy.deepcopy(STORED_ITEMS)
    for i in items:
        i["text"] = words.get(i["id"], i["text"])
    return items


def test_same_sources_leave_nothing_to_place():
    items = _fresh_items()
    stale = ground_delta.stale_ids(STORED_ITEMS, items)
    base, gone = ground_delta.base(STORED_DRAFT, stale)
    assert stale == set() and gone == [] and base == STORED_DRAFT
    assert ground_delta.unplaced(base, items) == [] and ground_delta.changed_context(STORED_ITEMS, items) == []


def test_a_new_request_strips_the_old_requirement_and_lists_only_the_new_items():
    items = _fresh_items(**{"req:R1": "show the plants in a list"})
    items.append({"id": "req:R2", "kind": "req", "text": "let me add a plant"})
    stale = ground_delta.stale_ids(STORED_ITEMS, items)
    base, gone = ground_delta.base(STORED_DRAFT, stale)
    assert stale == {"req:R1"}
    home = base["screens"][0]
    assert "req:R1" not in home["sources"] and [s["name"] for s in home["states"]] == ["loaded"]
    assert home["shows"] == [{"what": "plants to water today", "sources": ["api:GET /api/plants"]}]
    assert "screens/home/states/empty: left (no source left)" in gone
    assert [i["id"] for i in ground_delta.unplaced(base, items)] == ["req:R1", "req:R2"]
    section = ground_delta.placed_section(base, 3)
    assert section[0].startswith("Stored inventory v3") and any(line.startswith("- home (Home)") for line in section)
    task = ground_task.task({"name": "Demo", "product": "demo", "job": "water"}, "none",
                            ground_delta.unplaced(base, items), [], placed=section)
    assert f"## {ground_task.PLACED_TITLE}" in task and "req:R2" in task and "page:/list" not in task


def test_changed_words_on_a_placed_screen_are_context_for_the_delta():
    items = _fresh_items(**{"seen:list": "Plants | Fern | Basil | No plants saved yet"})
    assert [i["id"] for i in ground_delta.changed_context(STORED_ITEMS, items)] == ["seen:list"]
    assert ground_delta.stale_ids(STORED_ITEMS, items) == set()


ADDITIONS = {"screens": [{"id": "list", "name": "Plants", "sources": ["req:R2"],
                          "states": [{"name": "empty", "sources": ["seen:list"]}],
                          "actions": [{"id": "add", "what": "add a plant", "states": ["loaded", "empty"],
                                       "sources": ["req:R2"]}]},
                         {"id": "add-plant", "name": "Add a plant", "sources": ["req:R2"],
                          "states": [{"name": "form", "sources": ["req:R2"]}]}],
             "excluded": []}


def test_additions_merge_without_changing_a_stored_entry():
    assert contracts.check_json("ground_additions", ADDITIONS, "reply") == []
    merged = ground_delta.merge(STORED_DRAFT, ADDITIONS)
    assert ground_delta.kept(STORED_DRAFT, merged) == []
    assert contracts.check_json("ground_draft", merged, "merged") == []
    plants = merged["screens"][1]
    assert plants["sources"] == ["page:/list", "screen:list", "req:R2"]
    assert [s["name"] for s in plants["states"]] == ["loaded", "empty"]
    assert [s["id"] for s in merged["screens"]] == ["home", "list", "add-plant"]
    assert merged["screens"][0] == STORED_DRAFT["screens"][0]


@pytest.mark.parametrize("edit, where", [
    (lambda d: d["screens"].pop(0), "screens/home"),
    (lambda d: d["screens"][0].update(name="Start"), "screens/home"),
    (lambda d: d["screens"][0]["states"].reverse(), "screens/home/states"),
    (lambda d: d["screens"][0]["actions"][0].update(what="water all"), "screens/home/actions/water"),
    (lambda d: d["screens"][0]["shows"].clear(), "screens/home/shows"),
    (lambda d: d["excluded"].clear(), "excluded"),
])
def test_kept_check_catches_a_changed_stored_entry(edit, where):
    merged = copy.deepcopy(STORED_DRAFT)
    edit(merged)
    assert where in [p["where"] for p in ground_delta.kept(STORED_DRAFT, merged)]


# --- tool registry --------------------------------------------------------------------------------------------

def test_the_registry_holds_every_tool_it_names():
    out = tools_registry.check()
    assert out["tools"] >= 20 and out["per_stage"]["existing"] >= 4 and out["per_stage"]["build"] >= 3
    ids = {t["id"] for t in tools_registry.load()}
    for tool in ("capture_page", "design_measure", "design_page_checks", "app_instance", "product_app",
                 "existing_capture", "measure_in_page", "existing_sheet", "design_files", "capabilities",
                 "html_to_penpot", "design_pairwise_judge", "design_research", "showtell_pictures",
                 "check_integration", "check_showtell", "contact_sheet", "type_size_walker"):
        assert tool in ids
    assert "throwaway_app" not in ids


def _registry(tmp_path: Path, edit) -> Path:
    tools = copy.deepcopy(tools_registry.load())
    edit(tools)
    path = tmp_path / "tools.yaml"
    path.write_text(yaml.safe_dump({"tools": tools}), encoding="utf-8")
    return path


@pytest.mark.parametrize("edit, words", [
    (lambda t: t[0].update(path="configs/design/bin/no_such_tool.py"), "does not exist"),
    (lambda t: t[0].pop("job"), "missing job"),
    (lambda t: t[0].update(stages=["launch"]), "unknown stage"),
    (lambda t: t.append(copy.deepcopy(t[0])), "duplicate id"),
    (lambda t: t[0].update(path="/home/shinelay/design-lab/tool.py"), "relative to the repo"),
    (lambda t: t[0].pop("path"), "exactly one of path or url"),
])
def test_the_registry_fails_loud(tmp_path, edit, words):
    with pytest.raises(tools_registry.ToolsRegistryError, match=words):
        tools_registry.check(_registry(tmp_path, edit))


def test_stage_tasks_carry_the_existing_tools_section():
    section = tools_registry.task_section("ground")
    assert section[1] == f"## {tools_registry.TITLE}"
    assert any(line.startswith("- capabilities:") for line in section)
    task = ground_task.task({"name": "Demo", "product": "demo", "job": "water"}, "none", [], [], tools=section)
    assert tools_registry.TITLE in task
    with pytest.raises(tools_registry.ToolsRegistryError, match="unknown stage"):
        tools_registry.stage_tools("launch")
