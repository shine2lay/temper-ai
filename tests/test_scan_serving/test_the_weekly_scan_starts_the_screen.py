"""The Monday scan (configs/product/bin/weekly_scan.py) starts the early tech and serving screen.

After the new snapshot and its digest, the wrapper stages the snapshot's five files and the screen's
helpers into a fresh shared workspace and starts scan_serving there without waiting for it: the
scheduler stops a command after 30 minutes and the screen takes about an hour. A refused start leaves
the scan snapshot as it is and says so; SKIP_SERVING=1 skips the screen. The shared server, the
digest and the ACL calls are stand-ins: nothing here reaches Temper or a model.
"""

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "configs" / "product" / "bin"
ASSETS = ROOT / "configs" / "agents" / "scan_serving_assets"
SNAPSHOT = ("demand.md", "market.md", "timing.md", "shortlist.md", "grade.md")

# The wrapper imports server_run by its plain name, as its own helper tests do; share those modules.
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))
server = importlib.import_module("server_run")
weekly = importlib.import_module("weekly_scan")


class Monday:
    """One Monday's wrapper run: a shared scan that completes, then whatever the screen's start does."""

    def __init__(self, root, refuse_screen=False):
        self.root = root
        self.refuse_screen = refuse_screen
        self.started = []
        self.env = {"CADENCE_DIR": str(root / "cadence"), "HIST_DIR": str(root / "history"),
                    "DAILY_DIR": str(root / "daily"), "RUN_LOG_DIR": str(root / "logs"), "SKIP_SCAN": "0"}

    def launch(self, name, workflow, inputs, workspace):
        self.started.append({"name": name, "workflow": workflow, "workspace": workspace,
                             "inputs": json.loads(inputs.read_text()) if inputs else None})
        url = f"https://example/app/workflow/{name}"
        if workflow == "scan_market":
            scan = workspace / "state" / "scan"
            scan.mkdir(parents=True)
            for file in SNAPSHOT:
                (scan / file).write_text(f"fresh server {file}\n")
            server.save(server.filename(name, "done"), {"exit": 0, "cost": 4.2, "execution_id": name, "run_url": url})
        elif self.refuse_screen:
            raise server.Refused("another Product run is active")
        return {"name": name, "workspace": str(workspace), "run_url": url,
                "workflow_url": f"https://example/app/studio/{workflow}"}

    def subprocess_run(self, command, **kwargs):
        if "--out" in command:  # the cadence digest
            Path(command[command.index("--out") + 1]).write_text("weekly fixture digest\n")
            return Mock(returncode=0, stdout="fixture digest")
        assert command[0] == "setfacl", f"the wrapper must not wait on or run anything else: {command}"
        return Mock(returncode=0, stdout="")

    def main(self, **env):
        with patch.dict(server.os.environ, {**self.env, **env}), patch.object(server, "ROOT", self.root), \
                patch.object(server, "SHARED", self.root / "shared"), \
                patch.object(server, "launch", side_effect=self.launch), \
                patch.object(server, "prepare_workspace"), \
                patch.object(server.subprocess, "run", side_effect=self.subprocess_run):
            return weekly.main()

    def daily(self):
        return "".join(path.read_text() for path in (self.root / "daily").glob("*.md"))


@pytest.fixture
def monday(tmp_path):
    return Monday(tmp_path)


def test_the_screen_is_a_live_product_workflow():
    assert "scan_serving" in server.LIVE, "the launcher must treat it as live: no registration, one run at a time"


def test_the_new_snapshot_goes_to_a_fresh_screen_that_is_not_awaited(monday):
    assert monday.main() == 0
    assert [s["workflow"] for s in monday.started] == ["scan_market", "scan_serving"]
    screen = monday.started[1]
    workspace = screen["workspace"]
    assert screen["name"].startswith("weekly-serving-")
    assert workspace == monday.root / "shared" / screen["name"]
    snapshot = next((monday.root / "history").iterdir())
    for file in SNAPSHOT:
        assert (workspace / "inputs" / "baseline" / file).read_bytes() == (snapshot / file).read_bytes()
    for file in ("check_serving.py", "fixtures.json", "cite.py"):
        assert (workspace / "inputs" / "assets" / file).read_bytes() == (ASSETS / file).read_bytes()
    assert screen["inputs"] == {"baseline_dir": str(workspace / "inputs" / "baseline"),
                                "assets_dir": str(workspace / "inputs" / "assets"),
                                "cite_path": str(workspace / "inputs" / "assets" / "cite.py")}
    assert "serving screen started" in monday.daily() and f"/app/workflow/{screen['name']}" in monday.daily()


def test_skip_serving_leaves_the_scan_alone(monday):
    assert monday.main(SKIP_SERVING="1") == 0
    assert [s["workflow"] for s in monday.started] == ["scan_market"]
    assert "SKIP_SERVING=1" in monday.daily()


def test_a_refused_screen_keeps_the_snapshot_and_says_so(tmp_path):
    monday = Monday(tmp_path, refuse_screen=True)
    assert monday.main() == 1
    snapshot = next((tmp_path / "history").iterdir())
    assert (snapshot / "shortlist.md").read_text() == "fresh server shortlist.md\n"
    assert "NO serving screen started: another Product run is active" in monday.daily()


def test_an_existing_screen_workspace_is_never_reused(monday):
    scan_only = monday.launch

    def scan_then_someone_elses_workspace(name, workflow, inputs, workspace):
        job = scan_only(name, workflow, inputs, workspace)
        (workspace.parent / name.replace("weekly-scan-", "weekly-serving-")).mkdir()
        return job

    monday.launch = scan_then_someone_elses_workspace
    assert monday.main() == 1
    assert [s["workflow"] for s in monday.started] == ["scan_market"]
    assert "NO serving screen started" in monday.daily()
