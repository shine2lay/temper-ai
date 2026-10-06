"""The box profile (schema 2): compiled by the worker, stored on the row, checked by the box.

Model-free (G12): an on-disk sqlite database per test and no containers. What a sealed
box looks like from inside is tested with real containers in test_box_sealed_docker.py;
the worker's side (what it mounts, what it refuses) in test_docker_spawner.py.
"""

from __future__ import annotations

import argparse
import json
from unittest.mock import patch

import pytest
from sqlmodel import select

from temper_ai.cli.run_workflow import BOX_REFUSED_EXIT, cmd_run_workflow
from temper_ai.database import get_session, init_database, reset_database
from temper_ai.runner.execute import ExecuteResult
from temper_ai.runner.models import WorkflowRun
from temper_ai.runner.queue import queue_run
from temper_ai.spawner import box_profile
from temper_ai.spawner.box_profile import (
    BOUNDARY_ENV,
    LEGACY,
    METADATA_KEY,
    BoxIsStale,
    BoxProfileError,
    BoxStartRefused,
    DbProfileStore,
    check_row,
    compile_profile,
    digest_of,
    env_for,
    next_generation,
    record_for,
    stored_profile,
)
from temper_ai.spawner.box_view import SEALED, profile_from_env

PIN = {"dev": 1, "ino": 2, "type": "dir"}


#: What a sealed launch's classification adds (box_launches.Launch.as_dict + the engine check).
_SEALED_LAUNCH = {
    "files": {"configs/workflows/wf.yaml": "d" * 40},
    "configs": {"workflow": {"wf": "configs/workflows/wf.yaml"}},
    "allowed": {"agent_types": ["script"], "mcp_servers": [], "providers": [], "tools": []},
    "engine": {"sites": ["temper_ai/x.py::f"], "rules": "box-launches/2"},
    "classified_by": "box-launches/2",
    "label": "gate-classified; not reviewed by Security",
}


def _doc(boundary: str = LEGACY, generation: int = 1, **overrides) -> dict:
    facts = {
        "execution_id": "run-1", "generation": generation,
        "settings": box_profile.install_settings({BOUNDARY_ENV: boundary}),
        "boundary": boundary,
        "image": {"ref": "temper:test", "id": "sha256:" + "a" * 64},
        "source": {"code": {"from": "image", "digest": "sha256:" + "b" * 64}},
        "launch": {"workflow": "wf", "boundary": boundary, "digest": "sha256:" + "c" * 64,
                   **(_SEALED_LAUNCH if boundary == SEALED else {})},
        "grants": [{"target": "/app/workspace", "read_only": False, "pin": PIN}],
        "tmpfs": [],
        "runtime": {"interpreter": "/app/.venv/bin/python", "path": ["/usr/bin"],
                    "home": "/app", "user": "1000:1000"},
        "limits": {},
        "graph": box_profile.network_graph("temper-run-run-1", ["temper"], []),
        "legacy_mounts": ([{"source": "/srv/repo", "target": "/app/repo", "read_only": True,
                            "kind": "inherited", "class": "main repo copy"}]
                          if boundary == LEGACY else None),
    }
    facts.update(overrides)
    return compile_profile(**facts)


def _stored(*docs: dict) -> dict:
    """spawner_metadata after the worker stored ``docs`` one after another."""
    meta: dict = {}
    for doc in docs:
        meta[METADATA_KEY] = record_for(doc, stored_profile(meta))
    return meta


# -- settings ---------------------------------------------------------------------------------


def test_every_setting_defaults_to_how_boxes_were_before():
    assert box_profile.install_settings({}) == {
        BOUNDARY_ENV: "legacy", "TEMPER_BOX_SECRET_BOOTSTRAP": "env",
        "TEMPER_BOX_CAPABILITIES": "legacy", "TEMPER_BOX_STATE_ACCESS": "legacy",
        "TEMPER_BOX_TOOL_ISOLATION": "in_process", "TEMPER_BOX_MODEL_ACCESS": "direct",
    }


@pytest.mark.parametrize(("name", "value"), [
    (BOUNDARY_ENV, "closed"),
    ("TEMPER_BOX_SECRET_BOOTSTRAP", "broker"),
    ("TEMPER_BOX_STATE_ACCESS", "scoped"),
    ("TEMPER_BOX_MODEL_ACCESS", "gateway"),
])
def test_a_setting_for_something_not_built_refuses_every_run(name, value):
    with pytest.raises(BoxProfileError, match=name):
        box_profile.install_settings({name: value})


# -- compile ----------------------------------------------------------------------------------


def test_a_legacy_profile_says_it_is_partial_and_lists_what_it_leaves_open():
    doc = _doc()
    assert doc["schema_version"] == 2 and doc["hardening"] == "partial"
    steps = [r["step"] for r in doc["residuals"]]
    assert steps[0] == "BS1" and "main repo copy" in doc["residuals"][0]["what"]
    assert {"BS2", "BS3", "BS4", "BS5", "BS6", "network"} <= set(steps)
    assert doc["closure"]["network"] == "negative" and doc["closure"]["residual_edges"]
    assert doc["network_graph"][0]["class"].startswith("runner+tools (mixed")
    assert doc["label"].startswith("legacy") and "review" not in doc
    assert doc["classification"]["label"] == "not classified (a legacy box)"


def test_a_sealed_profile_is_partial_too():
    doc = _doc(SEALED)
    assert doc["hardening"] == "partial" and doc["rootfs"] == "read-only"
    assert {"BS2", "BS3", "BS4", "BS5", "BS6", "network"} <= {r["step"] for r in doc["residuals"]}
    assert "BS1" not in [r["step"] for r in doc["residuals"]]


# -- BS2: the one-shot delivery's section ------------------------------------------------------


def _oneshot_doc(boundary: str = SEALED, **overrides) -> dict:
    from temper_ai.spawner import box_bootstrap

    settings = box_profile.install_settings({BOUNDARY_ENV: SEALED,
                                             "TEMPER_BOX_SECRET_BOOTSTRAP": "oneshot"})
    section = box_bootstrap.section(names=["TEMPER_DATABASE_URL", "SYNTH_SERVICE_TOKEN"],
                                    uid=999, gid=999)
    return _doc(boundary, **{"settings": settings, "bootstrap": section, **overrides})


def test_oneshot_is_built_but_only_on_bs1s_sealed_profile():
    assert box_profile.install_settings({BOUNDARY_ENV: SEALED, "TEMPER_BOX_SECRET_BOOTSTRAP":
                                         "oneshot"})["TEMPER_BOX_SECRET_BOOTSTRAP"] == "oneshot"
    for boundary in (None, "legacy"):
        env = {"TEMPER_BOX_SECRET_BOOTSTRAP": "oneshot", **({BOUNDARY_ENV: boundary}
                                                           if boundary else {})}
        with pytest.raises(BoxProfileError, match="oneshot needs BS1's sealed profile"):
            box_profile.install_settings(env)


def test_a_oneshot_profile_carries_its_bounds_and_names_the_cli_tokens_exposure():
    doc = _oneshot_doc()
    boot = doc["bootstrap"]
    assert boot["mode"] == "oneshot" and boot["consumption"] == "once"
    assert boot["names"] == ["SYNTH_SERVICE_TOKEN", "TEMPER_DATABASE_URL"]
    assert set(boot["deadlines"]) == {"ready", "delivery", "ack"} and boot["max_bytes"] > 0
    assert doc["versions"]["bootstrap"] == "box-delivery/1"
    assert doc["label"] == box_profile.SEALED_ONESHOT_LABEL
    still = {r["step"]: r for r in doc["residuals"]}
    assert still["BS2"]["still"] == "partial"
    assert still["cli credential"]["still"] == "exposed"
    assert "BS2-partial, oneshot" in box_profile.summary(doc)


def test_an_env_profile_says_how_its_box_gets_its_secrets():
    doc = _doc(SEALED)
    assert doc["bootstrap"]["mode"] == "env" and doc["versions"]["bootstrap"] == "environment"
    assert next(r for r in doc["residuals"] if r["step"] == "BS2")["still"] != "partial"


@pytest.mark.parametrize(("change", "expect"), [
    ({"boundary": LEGACY}, "a one-shot delivery needs a sealed box"),
    ({"bootstrap": {"mode": "oneshot"}}, "one-shot delivery section is incomplete"),
])
def test_a_oneshot_profile_without_its_box_or_its_bounds_is_refused(change, expect):
    with pytest.raises(BoxProfileError, match=expect):
        _oneshot_doc(**change)


def test_a_sealed_profile_names_itself_gate_classified_and_its_residuals_by_name():
    """Security rm-963c1429 condition 5: never 'Security-reviewed', never a bare 'sealed'."""
    doc = _doc(SEALED)
    assert "review" not in doc
    assert doc["label"].startswith("sealed (BS1-partial): gate-classified, not reviewed by Security")
    for named in ("environment and memory secrets", "GitHub key", "BS2", "database and Redis",
                  "BS4", "BS5", "network"):
        assert named in doc["label"]
    assert doc["classification"] == {"by": "box-launches/2",
                                     "label": "gate-classified; not reviewed by Security"}
    still = {r["step"]: r["what"] for r in doc["residuals"]}
    assert "TEMPER_RUN_GITHUB_KEY" in still["BS2"] and "memory" in still["BS2"]
    assert "database" in still["BS4"] and "Redis" in still["BS4"]
    assert "network" in still["BS5"]
    assert "Security-reviewed" not in json.dumps(doc)


@pytest.mark.parametrize(("override", "expect"), [
    ({"image": {"ref": "temper:test", "id": "unknown"}}, "image.id"),
    ({"source": {}}, "source"),
    ({"source": {"code": {"from": "host"}}}, "source.code"),
    ({"grants": [{"target": "/app/workspace", "read_only": False, "pin": None}]},
     "grant /app/workspace"),
    ({"runtime": {"interpreter": "/x", "path": [], "home": "/app", "user": "1:1"}},
     "runtime.path"),
    ({"graph": []}, "network_graph"),
    ({"graph": [{"identity": {}}]}, "network_graph"),
    ({"launch": {"workflow": "wf", "boundary": "legacy"}}, "launch"),
    ({"launch": {**_SEALED_LAUNCH, "workflow": "wf", "boundary": "sealed"}}, "launch.digest"),
    ({"launch": {"workflow": "wf", "boundary": "sealed", "digest": "sha256:" + "c" * 64,
                 **{**_SEALED_LAUNCH, "allowed": {}}}}, "launch.allowed"),
    ({"launch": {"workflow": "wf", "boundary": "sealed", "digest": "sha256:" + "c" * 64,
                 **{**_SEALED_LAUNCH, "engine": None}}}, "launch.engine"),
    ({"launch": {"workflow": "wf", "boundary": "sealed", "digest": "sha256:" + "c" * 64,
                 **{**_SEALED_LAUNCH, "files": {}}}}, "launch.files"),
])
def test_a_sealed_profile_with_a_fact_missing_or_unknown_is_refused(override, expect):
    with pytest.raises(BoxProfileError, match="missing or unknown") as caught:
        _doc(SEALED, **override)
    assert expect in str(caught.value)


def test_the_box_gets_the_profile_and_checks_its_digest_and_generation():
    doc = _doc(SEALED, generation=3)
    env = env_for(doc)
    assert profile_from_env(env) == doc
    for name, value in [(box_profile.DIGEST_ENV, digest_of(_doc(SEALED))),
                        (box_profile.GENERATION_ENV, "4")]:
        with pytest.raises(BoxStartRefused):
            profile_from_env({**env, name: value})
    edited = json.loads(env[box_profile.PROFILE_ENV])
    edited["grants"].append({"target": "/app/repo", "read_only": True, "pin": PIN})
    with pytest.raises(BoxStartRefused, match="digest"):
        profile_from_env({**env, box_profile.PROFILE_ENV: json.dumps(edited)})
    with pytest.raises(BoxStartRefused, match="no profile"):
        profile_from_env({box_profile.DIGEST_ENV: env[box_profile.DIGEST_ENV]})


# -- what the row keeps -----------------------------------------------------------------------


def test_each_new_box_gets_the_next_generation_and_the_row_keeps_the_history():
    meta = _stored(_doc(generation=1), _doc(generation=2), _doc(generation=3))
    stored = stored_profile(meta)
    assert stored is not None and stored.generation == 3
    assert [h["generation"] for h in stored.history] == [1, 2]
    assert next_generation(stored, LEGACY) == 4 and next_generation(None, SEALED) == 1


def test_a_record_changed_outside_the_worker_is_refused():
    meta = _stored(_doc())
    meta[METADATA_KEY]["doc"]["boundary"] = SEALED
    with pytest.raises(BoxProfileError, match="digest"):
        stored_profile(meta)
    with pytest.raises(BoxProfileError, match="malformed"):
        stored_profile({METADATA_KEY: {"doc": {}}})


def test_a_run_that_was_ever_sealed_is_never_given_a_legacy_box():
    meta = _stored(_doc(SEALED, generation=1), _doc(SEALED, generation=2))
    with pytest.raises(BoxProfileError, match="fresh run"):
        next_generation(stored_profile(meta), LEGACY)
    assert box_profile.looks_sealed({"history": [{"boundary": SEALED}], "doc": "?"})


def test_check_row_lets_the_current_box_run_and_stops_older_ones():
    one, two = _doc(SEALED, generation=1), _doc(SEALED, generation=2)
    meta = _stored(one, two)
    check_row(two, meta)
    with pytest.raises(BoxIsStale):
        check_row(one, meta)
    with pytest.raises(BoxIsStale):  # a legacy box a newer box took over from leaves too
        check_row(_doc(generation=1), _stored(_doc(generation=1), _doc(generation=2)))


@pytest.mark.parametrize("case", ["no profile", "other digest", "no record", "edited record"])
def test_check_row_refuses_a_sealed_box_that_is_not_the_rows(case):
    doc = _doc(SEALED, generation=2)
    meta = _stored(_doc(SEALED, generation=1), doc)
    box = doc
    if case == "no profile":
        box = None
    elif case == "other digest":
        box = _doc(SEALED, generation=2, tmpfs=["/tmp:size=1m"])
    elif case == "no record":
        meta = {}
    else:
        meta[METADATA_KEY]["doc"]["grants"] = []
    with pytest.raises(BoxStartRefused):
        check_row(box, meta)


def test_check_row_never_stops_a_legacy_box_for_its_profile():
    check_row(None, {})
    check_row(None, _stored(_doc()))
    check_row(_doc(), {})
    check_row(None, {METADATA_KEY: {"doc": "unreadable"}})


# -- nothing a run controls goes in ----------------------------------------------------------


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "profile.db"
    monkeypatch.setenv("TEMPER_DATABASE_URL", f"sqlite:///{db_path}")
    reset_database()
    init_database(f"sqlite:///{db_path}")
    yield db_path
    reset_database()


def _row(execution_id: str) -> WorkflowRun:
    with get_session() as session:
        row = session.exec(select(WorkflowRun).where(WorkflowRun.execution_id == execution_id)).one()
        session.expunge(row)
        return row


def test_whoever_queues_a_run_cant_hand_in_a_profile(isolated_db):
    forged = record_for(_doc(SEALED), None)
    queue_run("run-1", "wf", "/w/run-1", {}, extra={"box_profile": forged, "only": ["a"]})
    assert _row("run-1").spawner_metadata == {"only": ["a"]}


def test_a_resume_keeps_the_runs_profile_and_its_history(isolated_db):
    queue_run("run-1", "wf", "/w/run-1", {})
    store = DbProfileStore()
    store.save("run-1", record_for(_doc(), None), None)
    with get_session() as session:
        row = session.exec(select(WorkflowRun).where(WorkflowRun.execution_id == "run-1")).one()
        row.status = "failed"
        session.add(row)
    queue_run("run-1", "wf", "/w/run-1", {}, start="resume",
              extra={"box_profile": {"generation": 99}})
    meta = _row("run-1").spawner_metadata
    assert meta["start"] == "resume" and meta[METADATA_KEY]["generation"] == 1


def test_the_store_refuses_a_profile_when_another_box_stored_one_meanwhile(isolated_db):
    queue_run("run-1", "wf", "/w/run-1", {})
    store = DbProfileStore()
    store.save("run-1", record_for(_doc(), None), None)
    with pytest.raises(BoxProfileError, match="meanwhile"):
        store.save("run-1", record_for(_doc(), None), None)
    facts = store.load("run-1")
    assert facts is not None and facts.workflow_name == "wf"


def test_the_store_finds_runs_that_share_or_hold_a_workspace(isolated_db):
    queue_run("mine", "wf", "/w/tree/mine", {})
    queue_run("inside", "wf", "/w/tree/mine/sub", {})
    queue_run("above-active", "wf", "/w/tree", {})
    queue_run("same-done", "wf", "/w/tree/mine", {})
    queue_run("neighbour", "wf", "/w/tree/other", {})
    with get_session() as session:
        row = session.exec(select(WorkflowRun).where(WorkflowRun.execution_id == "same-done")).one()
        row.status = "completed"
        session.add(row)
    found = DbProfileStore().neighbours("mine", ["/w/tree/mine"])
    assert [f.split(" ")[0] for f in found] == ["above-active", "inside"]


# -- the box's own check in `temper run-workflow` ---------------------------------------------


def _queued(isolated_db, metadata: dict | None = None) -> str:
    with get_session() as session:
        session.add(WorkflowRun(execution_id="run-1", workflow_name="wf", workspace_path="/w",
                                inputs={}, status="queued", spawner_metadata=metadata or {}))
    return "run-1"


def _run(monkeypatch, env: dict[str, str]) -> tuple[int, bool]:
    for name in (BOUNDARY_ENV, box_profile.PROFILE_ENV, box_profile.DIGEST_ENV,
                 box_profile.GENERATION_ENV):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr("temper_ai.cli.run_workflow._start_mcp_manager", lambda config_dir: None)
    monkeypatch.setattr("temper_ai.cli.run_workflow._stop_mcp_manager", lambda: None)
    args = argparse.Namespace(execution_id="run-1", config_dir=None, debug=False)
    with (
        patch("temper_ai.runner.bootstrap.bootstrap_runner_context_from_env") as boot,
        patch("temper_ai.runner.execute.execute_workflow",
              return_value=ExecuteResult(exit_code=0, status="completed")),
    ):
        code = cmd_run_workflow(args)
    return code, boot.called


def test_a_sealed_install_runs_nothing_outside_a_sealed_box(isolated_db, monkeypatch):
    _queued(isolated_db)
    code, booted = _run(monkeypatch, {BOUNDARY_ENV: SEALED})
    assert (code, booted) == (BOX_REFUSED_EXIT, False)
    code, booted = _run(monkeypatch, {BOUNDARY_ENV: SEALED, **env_for(_doc())})
    assert (code, booted) == (BOX_REFUSED_EXIT, False)
    assert _row("run-1").status == "queued"


def test_a_sealed_box_with_an_edited_profile_loads_nothing(isolated_db, monkeypatch):
    doc = _doc(SEALED)
    _queued(isolated_db, _stored(doc))
    env = env_for(doc)
    env[box_profile.PROFILE_ENV] = env[box_profile.PROFILE_ENV].replace("/app/workspace", "/app")
    code, booted = _run(monkeypatch, {BOUNDARY_ENV: SEALED, **env})
    assert (code, booted) == (BOX_REFUSED_EXIT, False)


def _launch_on_disk(monkeypatch, tmp_path) -> dict:
    """A sealed launch whose one file is really there, where the box's guard reads it."""
    from temper_ai.spawner.box_launches import blob_id

    data = b"workflow:\n  name: wf\n  nodes: []\n"
    (tmp_path / "configs" / "workflows").mkdir(parents=True)
    (tmp_path / "configs" / "workflows" / "wf.yaml").write_bytes(data)
    monkeypatch.setattr("temper_ai.spawner.box_guard.CONFIGS_ROOT", str(tmp_path / "configs"))
    return {"workflow": "wf", "boundary": SEALED, "digest": "sha256:" + "c" * 64,
            **_SEALED_LAUNCH, "files": {"configs/workflows/wf.yaml": blob_id(data)}}


def test_a_sealed_box_whose_launch_files_changed_loads_nothing(isolated_db, monkeypatch,
                                                               tmp_path):
    launch = _launch_on_disk(monkeypatch, tmp_path)
    (tmp_path / "configs" / "workflows" / "wf.yaml").write_text("workflow: {name: other}\n")
    doc = _doc(SEALED, launch=launch)
    _queued(isolated_db, _stored(doc))
    monkeypatch.setattr("temper_ai.spawner.box_view.view_problems", lambda *a, **k: [])
    code, booted = _run(monkeypatch, {BOUNDARY_ENV: SEALED, **env_for(doc)})
    assert (code, booted) == (BOX_REFUSED_EXIT, False)


def test_a_sealed_box_the_row_does_not_hold_fails_the_run_before_any_tool(isolated_db, monkeypatch,
                                                                          tmp_path):
    launch = _launch_on_disk(monkeypatch, tmp_path)
    doc = _doc(SEALED, generation=1, launch=launch)
    _queued(isolated_db, _stored(_doc(SEALED, generation=1, tmpfs=["/tmp:size=1m"],
                                      launch=launch)))
    monkeypatch.setattr("temper_ai.spawner.box_view.view_problems", lambda *a, **k: [])
    with patch("temper_ai.runner.execute.execute_workflow") as execute:
        code, _ = _run(monkeypatch, {BOUNDARY_ENV: SEALED, **env_for(doc)})
    assert code == BOX_REFUSED_EXIT and not execute.called
    row = _row("run-1")
    assert row.status == "failed" and row.error["kind"] == "box"


def test_a_stale_box_leaves_the_run_alone(isolated_db, monkeypatch):
    _queued(isolated_db, _stored(_doc(generation=1), _doc(generation=2)))
    code, _ = _run(monkeypatch, env_for(_doc(generation=1)))
    assert code == BOX_REFUSED_EXIT
    assert _row("run-1").status == "queued"


def _probe(env: dict[str, str]) -> dict:
    """configs/agents/ci_box_env.yaml's script, run here with only ``env``."""
    import subprocess
    from pathlib import Path

    import yaml

    agent = Path(__file__).resolve().parents[2] / "configs" / "agents" / "ci_box_env.yaml"
    script = yaml.safe_load(agent.read_text())["agent"]["script_template"]
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60,
                         env={"PATH": "/usr/bin:/bin", **env}, check=False)
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_ci_box_env_checks_the_profile_and_prints_facts_only():
    doc = _doc()
    seen = _probe(env_for(doc))
    assert seen["profile_problems"] == []
    assert seen["profile"]["boundary"] == "legacy" and seen["profile"]["generation"] == 1
    assert seen["profile"]["digest"] == digest_of(doc)[:19]
    assert {"BS1", "BS2", "BS6", "network"} <= set(seen["profile"]["residuals"])

    tampered = {**env_for(doc), box_profile.DIGEST_ENV: digest_of(_doc(generation=2))}
    assert "the profile does not match its digest" in _probe(tampered)["profile_problems"]
    bare = _doc()
    bare["residuals"] = [r for r in bare["residuals"] if r["step"] != "BS4"]
    assert any("BS4" in p for p in _probe(env_for(bare))["profile_problems"])


def test_a_legacy_box_runs_as_before_with_or_without_a_readable_profile(isolated_db, monkeypatch):
    doc = _doc()
    _queued(isolated_db, _stored(doc))
    assert _run(monkeypatch, env_for(doc)) == (0, True)

    with get_session() as session:
        row = session.exec(select(WorkflowRun).where(WorkflowRun.execution_id == "run-1")).one()
        row.status = "queued"
        session.add(row)
    broken = {**env_for(doc), box_profile.DIGEST_ENV: "sha256:" + "0" * 64}
    assert _run(monkeypatch, broken) == (0, True)
