"""Product helper checks: fake status/config APIs only, never model request fixtures."""
import datetime as dt
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server_run as server


class ServerRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.workspace = self.root / "shared/run"
        self.workspace.mkdir(parents=True)
        self.root_patch = patch.object(server, "ROOT", self.root)
        self.shared_patch = patch.object(server, "SHARED", self.root / "shared")
        self.root_patch.start()
        self.shared_patch.start()
        self.acl_patch = patch.object(server, "prepare_workspace")
        self.acl_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.shared_patch.stop()
        self.acl_patch.stop()
        self.tmp.cleanup()

    def launch(self):
        with patch.object(server, "assert_script_only"), patch.object(server, "assert_idle"), \
                patch.object(server, "start_monitor"), patch.object(server, "api", return_value={
                    "execution_id": "11111111-1111-4111-8111-111111111111", "status": "queued"}):
            return server.launch("fixture", "scan_market", None, self.workspace, non_model=True)

    def test_pre_post_fence_and_identity(self):
        def api(method, route, body):
            job = server.load(server.filename("fixture", "job.json"))
            self.assertEqual(job["state"], "submitting")
            self.assertIsNone(job["execution_id"])
            self.assertEqual((method, route), ("POST", "/api/runs"))
            return {"execution_id": "11111111-1111-4111-8111-111111111111", "status": "queued"}
        with patch.object(server, "assert_script_only"), patch.object(server, "assert_idle"), \
                patch.object(server, "start_monitor"), patch.object(server, "api", side_effect=api) as post:
            job = server.launch("fixture", "scan_market", None, self.workspace, non_model=True)
            self.assertEqual(post.call_count, 1)
            self.assertIn(job["execution_id"], job["run_url"])

    def test_used_name_never_posts(self):
        self.launch()
        with patch.object(server, "assert_script_only"), patch.object(server, "api") as api:
            with self.assertRaises(server.Refused):
                server.launch("fixture", "scan_market", None, self.workspace, non_model=True)
            api.assert_not_called()

    def test_ambiguous_post_stays_fenced(self):
        with patch.object(server, "assert_script_only"), patch.object(server, "assert_idle"), \
                patch.object(server, "api", side_effect=OSError("lost response")) as post:
            with self.assertRaises(server.Refused):
                server.launch("fixture", "scan_market", None, self.workspace, non_model=True)
            self.assertEqual(post.call_count, 1)
        self.assertEqual(server.load(server.filename("fixture", "job.json"))["state"], "uncertain-submit")
        with self.assertRaises(server.Refused):
            server.assert_idle()
        self.assertFalse(server.filename("fixture", "done").exists())

    def test_monitor_start_failure_is_not_remote_failure(self):
        with patch.object(server, "assert_script_only"), patch.object(server, "assert_idle"), \
                patch.object(server, "api", return_value={"execution_id": "11111111-1111-4111-8111-111111111111",
                                                         "status": "queued"}), \
                patch.object(server, "start_monitor", side_effect=server.Refused("unit failed")):
            with self.assertRaises(server.Refused):
                server.launch("fixture", "scan_market", None, self.workspace, non_model=True)
        self.assertIsNotNone(server.load(server.filename("fixture", "job.json"))["execution_id"])
        self.assertFalse(server.filename("fixture", "done").exists())

    def test_poll_failure_cannot_finish_or_release(self):
        self.launch()
        with patch.object(server, "api", side_effect=server.APIError(503)):
            with self.assertRaises(server.Refused):
                server.monitor("fixture", once=True)
        self.assertFalse(server.filename("fixture", "done").exists())
        self.assertEqual(server.load(server.filename("fixture", "job.json"))["state"], "queued")

    def test_wait_then_failure_receipt_uses_server_cost(self):
        job = self.launch()
        for state in ("queued", "running", "waiting", "failed"):
            data = {"id": job["execution_id"], "workflow_name": "scan_market", "status": state,
                    "total_cost_usd": 1.234, "nodes": []}
            with patch.object(server, "api", return_value=data):
                rc = server.monitor("fixture", once=True)
            self.assertEqual(rc, 1 if state == "failed" else 75)
            self.assertEqual(server.filename("fixture", "done").exists(), state == "failed")
        done = server.load(server.filename("fixture", "done"))
        self.assertEqual(done["cost"], 1.234)
        self.assertEqual(done["server_status"], "failed")
        self.assertEqual(done["run_url"], job["run_url"])

    def test_identity_mismatch_never_finishes(self):
        self.launch()
        with patch.object(server, "api", return_value={"id": "wrong", "workflow_name": "scan_market",
                                                       "status": "completed", "nodes": []}):
            with self.assertRaises(server.Refused):
                server.refresh("fixture")
        self.assertFalse(server.filename("fixture", "done").exists())

    def test_completed_receipt(self):
        job = self.launch()
        with patch.object(server, "api", return_value={"id": job["execution_id"], "workflow_name": "scan_market",
                                                       "status": "completed", "total_cost_usd": 0, "nodes": []}):
            self.assertEqual(server.monitor("fixture", once=True), 0)
        self.assertEqual(server.load(server.filename("fixture", "done"))["exit"], 0)

    def test_local_paths_and_credentials_refused(self):
        with self.assertRaises(server.Refused):
            server.launch("bad", "scan_market", None, self.root, non_model=True)
        with self.assertRaises(server.Refused):
            server.no_secrets({"oauth_token": "not-allowed"})
        with self.assertRaises(server.Refused):
            server.no_secrets({"note": "sk-ant-not-allowed"})
        path = self.root / "inputs.json"
        path.write_text(json.dumps({"assets_dir": "/private/worktree"}))
        with self.assertRaises(server.Refused):
            server.launch("bad", "scan_market", path, self.workspace, non_model=True)

    def test_staging_preserves_source_and_refuses_overwrite(self):
        source = self.root / "source"
        source.mkdir()
        (source / "fixture.txt").write_text("constant\n")
        with patch.object(server.subprocess, "run", return_value=Mock()):
            result = server.stage(source, self.workspace, "_assets")
        self.assertEqual((source / "fixture.txt").read_text(), "constant\n")
        self.assertEqual((self.workspace / "_assets/fixture.txt").read_text(), "constant\n")
        self.assertEqual(len(result["files"]), 1)
        with self.assertRaises(server.Refused):
            server.stage(source, self.workspace, "_assets")
        with self.assertRaises(server.Refused):
            server.stage(source, self.workspace, "../../escape")

    def test_closure_and_stage_names_are_preserved(self):
        doc = {"workflow": {"name": "candidate", "description": "unchanged",
                "outputs": {"result": "panel.structured.value"}, "nodes": [
                    {"name": "panel", "type": "stage", "strategy": "leader", "agents": [
                        "lens", {"agent": "writer", "role": "leader"}]}]}}
        mapping = {("workflow", "candidate"): "product_fixture",
                   ("agent", "lens"): "product_lens", ("agent", "writer"): "product_writer"}
        self.assertEqual(set(server.refs(doc, "workflow")), {("agent", "lens"), ("agent", "writer")})
        rewritten = server.rewrite(doc, "workflow", mapping)
        self.assertEqual(rewritten["workflow"]["nodes"][0]["name"], "panel")
        self.assertEqual(rewritten["workflow"]["nodes"][0]["agents"][0], {"agent": "product_lens", "name": "lens"})
        self.assertEqual(rewritten["workflow"]["nodes"][0]["agents"][1]["name"], "writer")
        self.assertEqual(rewritten["workflow"]["outputs"], doc["workflow"]["outputs"])
        self.assertEqual(doc["workflow"]["name"], "candidate")

    def test_non_model_requires_explicit_script_configs(self):
        doc = {"workflow": {"name": "smoke", "nodes": [{"name": "one", "type": "agent", "agent": "probe"}]}}
        with patch.object(server, "config", side_effect=[doc, {"agent": {"name": "probe", "type": "llm"}}]):
            with self.assertRaises(server.Refused):
                server.assert_script_only("smoke")
        doc["workflow"]["nodes"][0]["overrides"] = {"type": "llm"}
        with patch.object(server, "config", return_value=doc):
            with self.assertRaises(server.Refused):
                server.assert_script_only("smoke")

    def test_shared_active_job_blocks_even_without_monitor(self):
        server.save(server.filename("orphan", "job.json"), {"name": "orphan", "state": "waiting"})
        with self.assertRaises(server.Refused):
            server.assert_idle()

    def test_server_active_job_blocks_even_without_local_record(self):
        with patch.object(server.subprocess, "run", return_value=Mock(stdout="")), \
                patch.object(server, "api", return_value={"runs": [{"id": "existing", "workflow_name": "desk_check"}], "total": 1}):
            with self.assertRaises(server.Refused):
                server.assert_idle()

    def test_register_complete_closure_and_refuse_existing_name(self):
        source = self.root / "candidate"
        source.mkdir()
        (source / "probe.yaml").write_text("agent:\n  name: probe\n  type: script\n  script_template: echo fixture\n")
        (source / "flow.yaml").write_text("workflow:\n  name: smoke\n  nodes:\n    - name: leaf\n      type: agent\n      agent: probe\n")
        definitions = {}
        posted = []
        def config(kind, name, base=None):
            if (kind, name) not in definitions:
                raise server.APIError(404)
            return definitions[(kind, name)]
        def api(method, route, body):
            self.assertEqual(method, "POST")
            kind, name = route.rsplit("/", 2)[-2:]
            definitions[(kind, name)] = body["config"]
            posted.append((kind, name))
            return {}
        receipt = self.root / "registered.json"
        with patch.object(Path, "home", return_value=self.root), \
                patch.object(server, "config", side_effect=config), patch.object(server, "api", side_effect=api):
            result = server.register(source, "smoke", "product_fixture", receipt)
            self.assertEqual(result["state"], "registered")
            self.assertEqual(len(posted), 2)
            self.assertEqual(posted[-1][0], "workflow")
            self.assertEqual(server.load(receipt)["configs"][-1]["type"], "workflow")
            with self.assertRaises(server.Refused):
                server.register(source, "smoke", "product_fixture", self.root / "duplicate.json")
            self.assertEqual(len(posted), 2)

    def test_model_headroom_fails_closed(self):
        sys.path.insert(0, str(Path.home() / "product-autopilot"))
        import digest as quota
        with patch.object(quota, "_pool", return_value={"ok": False, "headroom": True}):
            with self.assertRaises(server.Refused):
                server.launch("no-quota", "scan_market", None, self.workspace)
        self.assertFalse(server.filename("no-quota", "job.json").exists())

    def test_sanitizer_never_logs_outputs_or_inputs(self):
        result = server.safe_status({"id": "fixture", "status": "waiting", "input_data": {"private": "input"},
             "output_data": "not-status", "nodes": [{"name": "stage", "status": "running",
                 "agent": {"output": "not-status"}, "child_nodes": [{"name": "leaf", "status": "waiting"}]}]})
        self.assertNotIn("input_data", result)
        self.assertNotIn("output_data", result)
        self.assertEqual(result["nodes"][0]["nodes"][0]["status"], "waiting")
        self.assertEqual(server.safe_status({"nodes": [{"name": "leaf", "child_nodes": None}]})["nodes"][0]["nodes"], [])
        self.assertIn("/app/workflow/", server.links("smoke", "id")["run_url"])


class WeeklyTests(unittest.TestCase):
    def test_collects_only_the_server_workspace_and_preserves_history(self):
        import weekly_scan
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shared = root / "shared"
            history = root / "history"
            (root / "legacy").mkdir()
            (root / "legacy/old.md").write_text("must not be collected")
            def launch(name, workflow, inputs, workspace):
                source = workspace / "state/scan"
                source.mkdir(parents=True)
                (source / "market.md").write_text("fresh server output")
                server.save(server.filename(name, "done"), {"exit": 0, "cost": 0,
                    "execution_id": "fixture", "run_url": "https://example/app/workflow/fixture"})
                return {"name": name, "workspace": str(workspace), "run_url": "https://example/app/workflow/fixture",
                        "workflow_url": "https://example/app/studio/scan_market"}
            def make_digest(command, **kwargs):
                out = Path(command[command.index("--out") + 1])
                out.write_text("weekly fixture digest\n")
                return Mock(returncode=0, stdout="fixture digest")
            env = {"CADENCE_DIR": str(root / "cadence"), "HIST_DIR": str(history),
                   "DAILY_DIR": str(root / "daily"), "RUN_LOG_DIR": str(root / "logs"),
                   "SCAN_DIR": str(root / "legacy"), "SKIP_SCAN": "0", "SKIP_SERVING": "1"}
            with patch.dict(server.os.environ, env), patch.object(server, "ROOT", root), \
                    patch.object(server, "SHARED", shared), patch.object(server, "launch", side_effect=launch), \
                    patch.object(weekly_scan.subprocess, "run", side_effect=make_digest):
                self.assertEqual(weekly_scan.main(), 0)
                snapshot = next(history.iterdir())
                self.assertEqual((snapshot / "market.md").read_text(), "fresh server output")
                self.assertFalse((snapshot / "old.md").exists())
                self.assertEqual(json.loads((snapshot / "server-run.json").read_text())["execution_id"], "fixture")
                self.assertIn("/app/workflow/fixture", (snapshot / "digest.md").read_text())
                self.assertEqual(weekly_scan.main(), 1)  # no overwrite of first snapshot
                self.assertEqual((snapshot / "market.md").read_text(), "fresh server output")


class DigestSharedTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("product_digest", Path.home() / "product-autopilot/digest.py")
        self.digest = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.digest)
        self.tmp = tempfile.TemporaryDirectory()
        self.runs = Path(self.tmp.name)
        self.patch = patch.object(self.digest, "RUNS", self.runs)
        self.patch.start()
        (self.runs / "waiting.cmd").write_text("shared metadata\n")
        (self.runs / "waiting.job.json").write_text(json.dumps({"state": "waiting", "execution_id": "id",
            "run_url": "https://example/workflow/id", "cost": 0, "workspace": "shared"}))

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_waiting_is_not_died_and_cannot_collect(self):
        with patch.object(self.digest, "unit_active", return_value=False):
            jobs = self.digest.jobs(dt.datetime.now(self.digest.PT), 60)
            self.assertEqual(jobs[0]["server_status"], "waiting")
            self.assertTrue(jobs[0]["active"])
            self.assertEqual(jobs[0]["state"], "monitor-lost")
            with self.assertRaises(SystemExit):
                self.digest.collect("waiting")

    def test_terminal_collection_keeps_receipts(self):
        (self.runs / "waiting.job.json").write_text(json.dumps({"state": "completed", "execution_id": "id", "cost": 0}))
        (self.runs / "waiting.done").write_text(json.dumps({"exit": 0, "ended": "2026-10-03T00:00:00Z"}))
        with patch.object(self.digest, "unit_active", return_value=False):
            self.digest.collect("waiting")
        self.assertTrue((self.runs / "collected/waiting.job.json").exists())
        self.assertTrue((self.runs / "collected/waiting.done").exists())


if __name__ == "__main__":
    unittest.main()
