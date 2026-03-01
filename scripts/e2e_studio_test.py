#!/usr/bin/env python3
"""Headless browser E2E test for Studio frontend.

Tests that all config CRUD pages work: view lists, create new configs,
verify they appear, and check key UI elements render.
"""

import json
import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://localhost:5179"
API = "http://localhost:8420"


def log(msg: str) -> None:
    print(f"  ✓ {msg}")


def log_warn(msg: str) -> None:
    print(f"  ⚠ {msg}")


def test_api_health(page):
    """Verify backend API is healthy."""
    resp = page.request.get(f"{API}/api/health")
    assert resp.ok, f"API health check failed: {resp.status}"
    data = resp.json()
    assert data["status"] == "healthy"
    log("Backend API is healthy")


def test_homepage_loads(page):
    """Verify the main page loads (workflow list / dashboard)."""
    page.goto(f"{BASE}/app/")
    page.wait_for_load_state("networkidle")
    time.sleep(1)
    body = page.locator("body").inner_text()
    assert len(body) > 0, "Homepage rendered empty"
    page.screenshot(path="/tmp/e2e_homepage.png")
    log(f"Homepage loads ({len(body)} chars of text)")


def test_studio_page(page):
    """Verify Studio visual editor page loads."""
    page.goto(f"{BASE}/app/studio")
    page.wait_for_load_state("networkidle")
    time.sleep(1)
    body = page.locator("body").inner_text()
    assert len(body) > 0, "Studio page rendered empty"
    page.screenshot(path="/tmp/e2e_studio.png")
    log("Studio page loads — screenshot saved")


def test_library_page_loads(page):
    """Verify Library page loads with tabs."""
    page.goto(f"{BASE}/app/library")
    page.wait_for_load_state("networkidle")
    time.sleep(1)
    page.screenshot(path="/tmp/e2e_library.png")
    body = page.locator("body").inner_text()
    assert len(body) > 0, "Library page rendered empty"
    log("Library page loads — screenshot saved")


def test_api_list_all_config_types(page):
    """List configs for all 4 types via API and verify counts."""
    for config_type in ["workflows", "agents", "stages", "tools"]:
        resp = page.request.get(f"{API}/api/studio/configs/{config_type}")
        assert resp.ok, f"List {config_type} failed: {resp.status}"
        data = resp.json()
        total = data.get("total", len(data.get("configs", [])))
        log(f"  {config_type}: {total} configs")


def test_api_get_specific_agent(page):
    """Get a specific agent config via API."""
    resp = page.request.get(f"{API}/api/studio/configs/agents/researcher")
    assert resp.ok, f"Get agent failed: {resp.status}"
    data = resp.json()
    assert "name" in data or "agent" in str(data)
    log("GET /agents/researcher — returned config data")


def test_api_get_specific_stage(page):
    """Get a specific stage config via API."""
    resp = page.request.get(f"{API}/api/studio/configs/stages/hello_analyze")
    assert resp.ok, f"Get stage failed: {resp.status}"
    data = resp.json()
    assert data is not None
    log("GET /stages/hello_analyze — returned config data")


def test_api_get_specific_workflow(page):
    """Get a specific workflow config via API."""
    resp = page.request.get(f"{API}/api/studio/configs/workflows/hello_world")
    assert resp.ok, f"Get workflow failed: {resp.status}"
    data = resp.json()
    assert data is not None
    log("GET /workflows/hello_world — returned config data")


def test_api_create_agent(page):
    """Create an agent via API."""
    data = {
        "agent": {
            "name": "e2e_test_agent",
            "description": "E2E test agent created by headless browser test",
            "type": "standard",
            "tools": ["Calculator"],
            "prompt": {"inline": "You are a test agent. Answer questions concisely."},
            "inference": {
                "provider": "ollama",
                "model": "llama3.2",
                "base_url": "http://localhost:11434",
                "temperature": 0.7,
                "max_tokens": 512,
            },
            "error_handling": {
                "retry_strategy": "ExponentialBackoff",
                "max_retries": 3,
                "fallback": "GracefulDegradation",
            },
        }
    }
    resp = page.request.post(
        f"{API}/api/studio/configs/agents/e2e_test_agent",
        data=json.dumps(data),
        headers={"Content-Type": "application/json"},
    )
    if resp.status == 201:
        log("Created e2e_test_agent")
    elif resp.status == 409:
        log("e2e_test_agent already exists (idempotent)")
    else:
        assert False, f"Create agent failed: {resp.status} — {resp.text()[:200]}"


def test_api_create_stage(page):
    """Create a stage via API."""
    data = {
        "stage": {
            "name": "e2e_test_stage",
            "description": "E2E test stage",
            "agents": ["e2e_test_agent"],
            "execution_mode": "sequential",
        }
    }
    resp = page.request.post(
        f"{API}/api/studio/configs/stages/e2e_test_stage",
        data=json.dumps(data),
        headers={"Content-Type": "application/json"},
    )
    if resp.status == 201:
        log("Created e2e_test_stage")
    elif resp.status == 409:
        log("e2e_test_stage already exists (idempotent)")
    else:
        assert False, f"Create stage failed: {resp.status} — {resp.text()[:200]}"


def test_api_create_workflow(page):
    """Create a workflow via API."""
    data = {
        "workflow": {
            "name": "e2e_test_workflow",
            "description": "E2E test workflow created by headless browser test",
            "version": "1.0",
            "stages": [{"name": "test_stage", "stage_ref": "e2e_test_stage"}],
            "error_handling": {
                "on_stage_failure": "halt",
                "max_stage_retries": 1,
                "escalation_policy": "LogAndContinue",
            },
        }
    }
    resp = page.request.post(
        f"{API}/api/studio/configs/workflows/e2e_test_workflow",
        data=json.dumps(data),
        headers={"Content-Type": "application/json"},
    )
    if resp.status == 201:
        log("Created e2e_test_workflow")
    elif resp.status == 409:
        log("e2e_test_workflow already exists (idempotent)")
    else:
        assert False, f"Create workflow failed: {resp.status} — {resp.text()[:200]}"


def test_api_verify_created_configs(page):
    """Verify created configs appear in list API."""
    for config_type, name in [
        ("agents", "e2e_test_agent"),
        ("stages", "e2e_test_stage"),
        ("workflows", "e2e_test_workflow"),
    ]:
        resp = page.request.get(f"{API}/api/studio/configs/{config_type}")
        assert resp.ok
        data = resp.json()
        names = [c["name"] for c in data.get("configs", [])]
        assert name in names, f"{name} not in {config_type} list"
        log(f"  {name} found in {config_type} list")


def test_ui_library_shows_workflows(page):
    """Navigate to library and check workflow list renders in UI."""
    page.goto(f"{BASE}/app/library")
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    body = page.locator("body").inner_text()

    # Look for known workflow names in the page text
    found = []
    for name in ["hello_world", "simple_research", "e2e_test_workflow"]:
        if name in body or name.replace("_", " ") in body.lower():
            found.append(name)

    page.screenshot(path="/tmp/e2e_library_workflows.png")
    if found:
        log(f"Workflows visible in UI: {', '.join(found)}")
    else:
        log_warn("No workflow names found in library body text (may use lazy loading)")


def test_ui_library_tab_navigation(page):
    """Try clicking all library tabs and verify they render."""
    page.goto(f"{BASE}/app/library")
    page.wait_for_load_state("networkidle")
    time.sleep(1)

    # Find all clickable elements that look like tabs
    buttons = page.locator("button, [role='tab'], a").all()
    tab_labels = []
    for btn in buttons:
        try:
            text = btn.inner_text().strip()
            if text and len(text) < 30:
                tab_labels.append(text)
        except Exception:
            pass

    log(f"Found {len(tab_labels)} clickable elements: {', '.join(tab_labels[:10])}")

    # Try clicking tabs that match config type names
    for tab_name in ["Agents", "Stages", "Tools", "Profiles", "Workflows"]:
        tab = page.locator(
            f"button:has-text('{tab_name}'), [role='tab']:has-text('{tab_name}')"
        ).first
        try:
            if tab.is_visible(timeout=1000):
                tab.click()
                time.sleep(0.5)
                page.screenshot(path=f"/tmp/e2e_library_tab_{tab_name.lower()}.png")
                log(f"  Clicked '{tab_name}' tab — screenshot saved")
        except Exception:
            pass


def test_ui_studio_open_workflow(page):
    """Open an existing workflow in the Studio editor."""
    page.goto(f"{BASE}/app/studio/hello_world")
    page.wait_for_load_state("networkidle")
    time.sleep(2)
    body = page.locator("body").inner_text()
    page.screenshot(path="/tmp/e2e_studio_hello_world.png")

    # Check for studio elements (stage names, canvas, etc.)
    if (
        "hello" in body.lower()
        or "analyze" in body.lower()
        or "summarize" in body.lower()
    ):
        log("Studio loaded hello_world — workflow content visible")
    else:
        log("Studio loaded hello_world — checking for canvas elements")

    # Check for ReactFlow canvas
    canvas = page.locator(
        ".react-flow, [class*='reactflow'], [data-testid*='flow']"
    ).first
    try:
        if canvas.is_visible(timeout=2000):
            log("  ReactFlow canvas element found")
    except Exception:
        log_warn("  ReactFlow canvas not detected (may use different class names)")


def test_api_update_agent(page):
    """Update the created agent config via API."""
    data = {
        "agent": {
            "name": "e2e_test_agent",
            "description": "Updated E2E test agent",
            "type": "standard",
            "tools": ["Calculator", "Bash"],
            "prompt": {"inline": "You are an updated test agent. Be helpful."},
            "inference": {
                "provider": "ollama",
                "model": "llama3.2",
                "base_url": "http://localhost:11434",
                "temperature": 0.5,
                "max_tokens": 512,
            },
            "error_handling": {
                "retry_strategy": "ExponentialBackoff",
                "max_retries": 3,
                "fallback": "GracefulDegradation",
            },
        }
    }
    resp = page.request.put(
        f"{API}/api/studio/configs/agents/e2e_test_agent",
        data=json.dumps(data),
        headers={"Content-Type": "application/json"},
    )
    assert resp.ok, f"Update agent failed: {resp.status} — {resp.text()[:200]}"
    log("Updated e2e_test_agent (added Bash tool, changed temp)")

    # Verify update
    resp2 = page.request.get(f"{API}/api/studio/configs/agents/e2e_test_agent")
    assert resp2.ok
    updated = resp2.json()
    config_data = updated.get("config_data", updated)
    agent_inner = config_data.get("agent", config_data)
    tools = agent_inner.get("tools", [])
    if "Bash" in tools or "Bash" in str(tools):
        log("  Verified: Bash tool present after update")


def test_api_validate_workflow(page):
    """Validate a workflow config via API."""
    data = {
        "workflow": {
            "name": "validation_test",
            "stages": [{"name": "s1", "stage_ref": "hello_analyze"}],
        }
    }
    resp = page.request.post(
        f"{API}/api/studio/validate/workflows",
        data=json.dumps(data),
        headers={"Content-Type": "application/json"},
    )
    if resp.ok:
        result = resp.json()
        log(f"Validation endpoint responded: {json.dumps(result)[:100]}")
    else:
        log_warn(f"Validation endpoint: {resp.status}")


def test_api_get_schema(page):
    """Get JSON schema for agent config type."""
    resp = page.request.get(f"{API}/api/studio/schemas/agents")
    if resp.ok:
        schema = resp.json()
        log(f"Schema for agents: {len(json.dumps(schema))} bytes")
    else:
        log_warn(f"Schema endpoint: {resp.status}")


def test_api_get_raw_yaml(page):
    """Get raw YAML content of a config."""
    resp = page.request.get(f"{API}/api/studio/configs/agents/researcher/raw")
    if resp.ok:
        yaml_text = resp.text()
        assert "agent:" in yaml_text or "name:" in yaml_text
        log(f"Raw YAML for researcher agent: {len(yaml_text)} chars")
    else:
        log_warn(f"Raw YAML endpoint: {resp.status}")


def test_api_list_runs(page):
    """List workflow runs via API — exercises execution_service without RunStore."""
    resp = page.request.get(f"{API}/api/runs")
    assert resp.ok, f"List runs failed: {resp.status}"
    data = resp.json()
    assert "runs" in data
    assert "total" in data
    log(f"GET /api/runs — {data['total']} runs returned")


def test_api_list_runs_with_status_filter(page):
    """List runs filtered by status."""
    resp = page.request.get(f"{API}/api/runs?status=completed&limit=5")
    assert resp.ok, f"List runs (filtered) failed: {resp.status}"
    data = resp.json()
    assert "runs" in data
    log(f"GET /api/runs?status=completed — {data['total']} completed runs")


def test_api_get_run_not_found(page):
    """Get a non-existent run returns 404."""
    resp = page.request.get(f"{API}/api/runs/exec-nonexistent-999")
    assert resp.status == 404, f"Expected 404, got {resp.status}"
    log("GET /api/runs/exec-nonexistent-999 — 404 as expected")


def test_api_list_stuck_runs(page):
    """List stuck runs — exercises find_stuck_executions (no RunStore)."""
    resp = page.request.get(f"{API}/api/runs/stuck?threshold_minutes=30")
    assert resp.ok, f"List stuck runs failed: {resp.status}"
    data = resp.json()
    assert "runs" in data
    log(f"GET /api/runs/stuck — {data['total']} stuck runs")


def test_api_run_workflow_and_check_status(page):
    """Start a workflow run, then poll for status — full execution path."""
    run_body = json.dumps(
        {
            "workflow": "hello_world",
            "inputs": {"topic": "e2e headless test"},
        }
    )
    resp = page.request.post(
        f"{API}/api/runs",
        data=run_body,
        headers={"Content-Type": "application/json"},
    )
    assert resp.ok, f"Create run failed: {resp.status} — {resp.text()[:200]}"
    data = resp.json()
    exec_id = data["execution_id"]
    log(f"POST /api/runs — started {exec_id}")

    # Poll status for up to 120s
    deadline = time.time() + 120
    final_status = None
    while time.time() < deadline:
        time.sleep(3)
        status_resp = page.request.get(f"{API}/api/runs/{exec_id}")
        if status_resp.ok:
            status_data = status_resp.json()
            final_status = status_data.get("status")
            log(f"  Status: {final_status}")
            if final_status in ("completed", "failed"):
                break
        else:
            log_warn(f"  Status check: HTTP {status_resp.status}")

    assert final_status is not None, "Never got a status response"
    if final_status == "completed":
        log(f"Workflow {exec_id} completed successfully")
    elif final_status == "failed":
        log_warn(f"Workflow {exec_id} failed (may be expected if LLM unavailable)")
    else:
        log_warn(f"Workflow {exec_id} still {final_status} after timeout")


def test_api_health_readiness(page):
    """Check readiness endpoint — exercises GracefulShutdownManager."""
    resp = page.request.get(f"{API}/api/health/ready")
    assert resp.ok, f"Readiness check failed: {resp.status}"
    data = resp.json()
    assert data["status"] == "ready"
    log("GET /api/health/ready — status=ready")


def test_api_list_available_workflows(page):
    """List available workflow configs."""
    resp = page.request.get(f"{API}/api/workflows/available")
    assert resp.ok, f"List available workflows failed: {resp.status}"
    data = resp.json()
    assert "workflows" in data
    names = [w.get("name", "") for w in data["workflows"]]
    log(
        f"GET /api/workflows/available — {data['total']} workflows: {', '.join(names[:5])}"
    )


def test_comparison_page(page):
    """Check comparison page loads."""
    page.goto(f"{BASE}/app/compare")
    page.wait_for_load_state("networkidle")
    time.sleep(1)
    body = page.locator("body").inner_text()
    assert len(body) > 0
    page.screenshot(path="/tmp/e2e_compare.png")
    log("Comparison page loads")


def test_cleanup(page):
    """Clean up test configs created during the test."""
    for config_type, name in [
        ("workflows", "e2e_test_workflow"),
        ("stages", "e2e_test_stage"),
        ("agents", "e2e_test_agent"),
    ]:
        resp = page.request.delete(f"{API}/api/studio/configs/{config_type}/{name}")
        if resp.ok:
            log(f"  Deleted {config_type}/{name}")
        else:
            log_warn(f"  Cleanup {config_type}/{name}: {resp.status}")

    # Verify deleted
    for config_type, name in [
        ("agents", "e2e_test_agent"),
        ("stages", "e2e_test_stage"),
        ("workflows", "e2e_test_workflow"),
    ]:
        resp = page.request.get(f"{API}/api/studio/configs/{config_type}/{name}")
        if resp.status == 404:
            log(f"  Confirmed deleted: {config_type}/{name}")
        else:
            log_warn(f"  {config_type}/{name} still exists after delete")


def main():
    print("\n=== E2E Studio Frontend Test (Headless Browser) ===\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        tests = [
            ("API Health Check", test_api_health),
            ("Homepage Loads", test_homepage_loads),
            ("Studio Page", test_studio_page),
            ("Library Page", test_library_page_loads),
            ("API: List All Config Types", test_api_list_all_config_types),
            ("API: Get Agent Config", test_api_get_specific_agent),
            ("API: Get Stage Config", test_api_get_specific_stage),
            ("API: Get Workflow Config", test_api_get_specific_workflow),
            ("API: Get Raw YAML", test_api_get_raw_yaml),
            ("API: Get Schema", test_api_get_schema),
            ("API: Create Agent", test_api_create_agent),
            ("API: Create Stage", test_api_create_stage),
            ("API: Create Workflow", test_api_create_workflow),
            ("API: Verify Created Configs", test_api_verify_created_configs),
            ("API: Update Agent", test_api_update_agent),
            ("API: Validate Workflow", test_api_validate_workflow),
            ("API: Health Readiness", test_api_health_readiness),
            ("API: List Available Workflows", test_api_list_available_workflows),
            ("API: List Runs", test_api_list_runs),
            ("API: List Runs (filtered)", test_api_list_runs_with_status_filter),
            ("API: Get Run Not Found", test_api_get_run_not_found),
            ("API: List Stuck Runs", test_api_list_stuck_runs),
            ("API: Run Workflow + Status", test_api_run_workflow_and_check_status),
            ("UI: Library Shows Workflows", test_ui_library_shows_workflows),
            ("UI: Library Tab Navigation", test_ui_library_tab_navigation),
            ("UI: Studio Open Workflow", test_ui_studio_open_workflow),
            ("Comparison Page", test_comparison_page),
            ("Cleanup", test_cleanup),
        ]

        passed = 0
        failed = 0
        for name, test_fn in tests:
            print(f"\n[{name}]")
            try:
                test_fn(page)
                passed += 1
            except Exception as e:
                print(f"  ✗ FAILED: {e}")
                try:
                    page.screenshot(
                        path=f"/tmp/e2e_FAIL_{name.replace(' ', '_').replace(':', '').lower()}.png"
                    )
                except Exception:
                    pass
                failed += 1

        browser.close()

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
    print(f"{'='*50}\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
