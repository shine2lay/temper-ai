"""Product helper checks: fake status/config APIs only, never model request fixtures."""
import datetime as dt
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server_run as server


class WriterKeyTests(unittest.TestCase):
    """Temper's write guard names Product only on writes; the key never leaves its header."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.key_file = Path(self.tmp.name) / "product.key"
        self.key_file.write_text("fixture-key-value\n")
        self.sent = []

    def tearDown(self):
        self.tmp.cleanup()

    def fake_urlopen(self, request, timeout=None):
        self.sent.append(request)
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read = Mock(return_value=b"{}")
        return response

    def call(self, method, env):
        with patch.dict("os.environ", env, clear=False), \
                patch.object(server.urllib.request, "urlopen", self.fake_urlopen):
            server.api(method, "/api/runs", {"workflow": "w"} if method != "GET" else None)
        return self.sent[-1]

    def test_writes_send_the_key_from_the_named_file(self):
        for method in ("POST", "PUT", "DELETE"):
            request = self.call(method, {"TEMPER_API_KEY_FILE": str(self.key_file)})
            self.assertEqual(request.get_header("Authorization"), "Bearer fixture-key-value")

    def test_reads_send_no_key(self):
        request = self.call("GET", {"TEMPER_API_KEY_FILE": str(self.key_file)})
        self.assertIsNone(request.get_header("Authorization"))

    def test_default_file_when_no_env(self):
        env = {k: v for k, v in os.environ.items() if k != "TEMPER_API_KEY_FILE"}
        with patch.dict("os.environ", env, clear=True), patch.object(server, "KEY_FILE", self.key_file):
            self.assertEqual(server.auth_headers("POST"), {"Authorization": "Bearer fixture-key-value"})

    def test_missing_or_empty_file_sends_no_header_and_still_writes(self):
        request = self.call("POST", {"TEMPER_API_KEY_FILE": str(Path(self.tmp.name) / "absent.key")})
        self.assertIsNone(request.get_header("Authorization"))
        self.key_file.write_text("  \n")
        request = self.call("POST", {"TEMPER_API_KEY_FILE": str(self.key_file)})
        self.assertIsNone(request.get_header("Authorization"))

    def test_a_refused_write_never_shows_the_key(self):
        def refuse(request, timeout=None):
            raise server.urllib.error.HTTPError(request.full_url, 401, "no", {}, None)
        with patch.dict("os.environ", {"TEMPER_API_KEY_FILE": str(self.key_file)}), \
                patch.object(server.urllib.request, "urlopen", refuse):
            with self.assertRaises(server.APIError) as caught:
                server.api("POST", "/api/runs", {"workflow": "w"})
        self.assertEqual(caught.exception.status, 401)
        self.assertNotIn("fixture-key-value", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)


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

    def test_own_unit_is_not_another_workflow(self):
        # The weekly cadence launches from inside its own product-weekly-cadence-* unit (#19 hand-off);
        # on 2026-10-05 it refused itself. Its own unit is skipped; any other product unit still blocks.
        own = "product-weekly-cadence-2026-10-05.service"
        line = f"{own} loaded active running Product weekly cadence\n"
        with patch.object(server, "own_unit", return_value=own), \
                patch.object(server.subprocess, "run", return_value=Mock(stdout=line)), \
                patch.object(server, "api", return_value={"runs": [], "total": 0}):
            server.assert_idle()
        other = line + "product-desk-c9.service loaded active running monitor\n"
        with patch.object(server, "own_unit", return_value=own), \
                patch.object(server.subprocess, "run", return_value=Mock(stdout=other)), \
                patch.object(server, "api", return_value={"runs": [], "total": 0}):
            with self.assertRaises(server.Refused) as caught:
                server.assert_idle()
        self.assertIn("product-desk-c9.service", str(caught.exception))
        with patch.object(server, "own_unit", return_value=None), \
                patch.object(server.subprocess, "run", return_value=Mock(stdout=line)), \
                patch.object(server, "api", return_value={"runs": [], "total": 0}):
            with self.assertRaises(server.Refused):
                server.assert_idle()

    def test_own_unit_reads_the_service_from_cgroup(self):
        text = "0::/user.slice/user-1000.slice/user@1000.service/app.slice/product-weekly-cadence-2026-10-05.service\n"
        with patch.object(server.Path, "read_text", return_value=text):
            self.assertEqual(server.own_unit(), "product-weekly-cadence-2026-10-05.service")
        with patch.object(server.Path, "read_text", return_value="0::/user.slice/user-1000.slice/session-3.scope\n"):
            self.assertIsNone(server.own_unit())
        with patch.object(server.Path, "read_text", side_effect=OSError):
            self.assertIsNone(server.own_unit())

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


class LiveConsumerBriefTests(unittest.TestCase):
    """Queue #48: the deployed consumer brief is a live Product workflow like the business brief.

    #39 found opportunity_brief_consumer missing from LIVE: start.sh asked for a registration receipt to
    launch it by name, and assert_idle did not see a consumer brief going on the server. Fake server,
    units and quota only: nothing is submitted and no model is called.
    """

    BEFORE = {"scan_market", "scan_serving", "signal_harvest", "signal_grade", "opportunity_brief", "desk_check",
              "shape_mvp", "pmf_evidence", "feature_screen", "confidence_check"}  # LIVE before #48; none drops out
    EXECUTION = "22222222-2222-4222-8222-222222222222"
    CANDIDATE = "product_q48_opportunity_brief_consumer_0123456789"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.workspace = self.root / "shared/run"
        self.workspace.mkdir(parents=True)
        self.calls = []  # (method, route) in order
        self.bodies = []  # every run start the fake server got
        self.active = {}  # status -> the runs the fake server lists for it
        self.configs = {}  # (kind, name) -> the definition the fake server holds
        quota = types.SimpleNamespace(load=lambda path, default: default,
                                      _pool=lambda threshold: {"ok": True, "headroom": True})
        for patcher in (patch.object(server, "ROOT", self.root), patch.object(server, "SHARED", self.root / "shared"),
                        patch.object(server, "prepare_workspace"), patch.object(server, "start_monitor"),
                        patch.object(server, "api", side_effect=self.api),
                        patch.object(server.subprocess, "run", return_value=Mock(stdout="")),
                        patch.dict(sys.modules, {"digest": quota})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def api(self, method, route, body=None, base=None):
        self.calls.append((method, route))
        if (method, route) == ("POST", "/api/runs"):
            self.bodies.append(body)
            return {"execution_id": self.EXECUTION, "status": "queued"}
        if method == "GET" and route.startswith("/api/workflows?"):
            runs = self.active.get(urllib.parse.parse_qs(route.split("?", 1)[1])["status"][0], [])
            return {"runs": runs, "total": len(runs)}
        if method == "GET" and route.startswith("/api/studio/configs/"):
            key = tuple(route.rsplit("/", 2)[-2:])
            if key not in self.configs:
                raise server.APIError(404)
            return {"config": self.configs[key]}
        raise AssertionError(f"unexpected fake API call {method} {route}")

    def running(self, name, state="running"):
        return {state: [{"id": "33333333-3333-4333-8333-333333333333", "workflow_name": name}]}

    def test_consumer_brief_launches_by_name_without_a_receipt_when_idle(self):
        job = server.launch("consumer-brief", "opportunity_brief_consumer", None, self.workspace)
        self.assertEqual((job["execution_id"], job["state"]), (self.EXECUTION, "queued"))
        self.assertIsNone(job["candidate_receipt"])
        self.assertEqual([body["workflow"] for body in self.bodies], ["opportunity_brief_consumer"])
        self.assertEqual(server.load(server.filename("consumer-brief", "job.json"))["workflow"],
                         "opportunity_brief_consumer")
        # The real one-at-a-time check asked the server for every active state; no receipt was looked up.
        asked = [route for _, route in self.calls if route.startswith("/api/workflows?")]
        self.assertEqual([urllib.parse.parse_qs(route.split("?", 1)[1])["status"][0] for route in asked],
                         ["pending", "queued", "running", "waiting"])
        self.assertFalse([route for _, route in self.calls if route.startswith("/api/studio/configs/")])

    def test_an_active_consumer_brief_refuses_another_product_launch(self):
        # Started outside this helper (no local job record): only the server's run list shows it.
        for state in ("pending", "queued", "running", "waiting"):
            self.active = self.running("opportunity_brief_consumer", state)
            with self.subTest(state=state):
                with self.assertRaises(server.Refused) as caught:
                    server.assert_idle()
                self.assertIn(f"still {state}: 33333333-3333-4333-8333-333333333333", str(caught.exception))
                for workflow in ("opportunity_brief_consumer", "scan_market"):
                    name = f"next-{state}-{workflow.split('_')[0]}"
                    with self.assertRaises(server.Refused) as caught:
                        server.launch(name, workflow, None, self.workspace)
                    self.assertIn("shared Product execution still", str(caught.exception))
                    self.assertFalse(server.filename(name, "job.json").exists())
        self.assertEqual(self.bodies, [])

    def test_every_other_live_name_still_fences_and_other_runs_do_not(self):
        self.assertLessEqual(self.BEFORE | {"opportunity_brief_consumer"}, server.LIVE)
        for name in [*sorted(self.BEFORE), self.CANDIDATE]:
            self.active = self.running(name)
            with self.subTest(active=name), self.assertRaises(server.Refused):
                server.assert_idle()
        # Not Product's: another department's workflow, or a local name that was never registered.
        for name in ("epd_build", "opportunity_brief_consumer_next"):
            self.active = self.running(name)
            with self.subTest(active=name):
                server.assert_idle()

    def test_candidates_still_need_their_matching_receipt(self):
        definition = {"workflow": {"name": self.CANDIDATE, "nodes": []}}
        self.configs = {("workflow", self.CANDIDATE): definition}
        receipt = self.root / "registration.json"
        server.save(receipt, {"state": "registered", "workflow": self.CANDIDATE, "configs": [
            {"type": "workflow", "name": self.CANDIDATE, "sha256": server.digest(definition)}]})
        partial = self.root / "partial.json"
        server.save(partial, {**server.load(receipt), "state": "registering"})
        other = self.root / "other.json"
        server.save(other, {**server.load(receipt), "workflow": "product_q48_other_0123456789"})
        refused = [("opportunity_brief_consumer_next", None), (self.CANDIDATE, None),
                   (self.CANDIDATE, partial), (self.CANDIDATE, other)]
        for index, (workflow, given) in enumerate(refused):
            with self.subTest(workflow=workflow, receipt=given):
                with self.assertRaises(server.Refused) as caught:
                    server.launch(f"candidate-{index}", workflow, None, self.workspace, receipt=given)
                self.assertIn("receipt", str(caught.exception))
        self.configs[("workflow", self.CANDIDATE)] = {"workflow": {"name": self.CANDIDATE, "nodes": [{"name": "x"}]}}
        with self.assertRaises(server.Refused) as caught:
            server.launch("candidate-changed", self.CANDIDATE, None, self.workspace, receipt=receipt)
        self.assertIn("changed since registration", str(caught.exception))
        self.assertEqual(self.bodies, [])
        self.assertFalse(list((self.root / "runs").glob("candidate-*")))
        self.configs[("workflow", self.CANDIDATE)] = definition
        job = server.launch("candidate-ok", self.CANDIDATE, None, self.workspace, receipt=receipt)
        self.assertEqual(job["candidate_receipt"], str(receipt))
        self.assertEqual([body["workflow"] for body in self.bodies], [self.CANDIDATE])


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
        autopilot = Path.home() / "product-autopilot"
        spec = importlib.util.spec_from_file_location("product_digest", autopilot / "digest.py")
        self.digest = importlib.util.module_from_spec(spec)
        # digest.py imports its siblings (report_policy) from its own folder.
        with patch.object(sys, "path", [str(autopilot), *sys.path]):
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
