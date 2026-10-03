#!/usr/bin/env python3
"""Queue 14 evidence from application metadata and file hashes, never model payloads."""
import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

import server_run as server

RESULTS = Path.home() / "product-autopilot/results/visibility-14"
FROZEN = [Path.home() / "temper-ai-serve-screen-9/configs/agents/local",
          Path.home() / "temper-ai-serve-screen-9/configs/workflows/local",
          Path.home() / "temper-ai-serve-screen-10/configs/agents/local",
          Path.home() / "temper-ai-serve-screen-10/configs/workflows/local",
          Path.home() / "product-autopilot/results/2026-10-02-serving-9"]


def hashes():
    result = {}
    for root in FROZEN:
        for path in sorted(root.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                result[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def registrations():
    result = {}
    for kind in ("workflow", "agent", "stage"):
        listing = server.api("GET", f"/api/studio/configs/{kind}")["configs"]
        for entry in listing:
            name = entry if isinstance(entry, str) else entry["name"]
            if not name.startswith("product_q14_") and name not in {"product_visibility_smoke", "product_visibility_probe"}:
                try:
                    content_hash = server.digest(server.config(kind, name))
                except server.APIError as exc:
                    # An existing unreadable config is not permission to repair another owner.
                    content_hash = f"unreadable:HTTP{exc.status}"
                result[f"{kind}/{name}"] = {"content": content_hash, "metadata": server.digest(entry)}
    return result


def baseline():
    data = {"created": server.now(), "frozen": hashes(), "registrations": registrations(),
            "credential_file_hash": hashlib.sha256((Path.home() / "temper-ai/.env").read_bytes()).hexdigest()}
    server.save(RESULTS / "before-integrity.json", data)
    print(json.dumps({"frozen_files": len(data["frozen"]), "unrelated_configs": len(data["registrations"]),
                      "unreadable_names": [name for name, value in data["registrations"].items()
                                           if value["content"].startswith("unreadable:")]}))


def verify(name, receipt):
    job = server.load(server.filename(name, "job.json"))
    reg = server.load(receipt)
    status = server.safe_status(server.api("GET", "/api/workflows/" + job["execution_id"]))
    checks = {
        "completed": status["status"] == "completed",
        "matching_id": status["id"] == job["execution_id"],
        "matching_workflow": status["workflow_name"] == reg["workflow"] == job["workflow"],
        "completed_nodes": [(n["name"], n["status"]) for n in status["nodes"]]
                           == [("prepare", "completed"), ("write", "completed"), ("check", "completed")],
        "zero_models": status["total_llm_calls"] == 0 and status["total_tokens"] == 0,
        "zero_cost": status["total_cost_usd"] == 0,
        "shared_workspace": status["workspace_path"] == job["workspace"],
        "config_survived_worker": all(server.digest(server.config(c["type"], c["name"])) == c["sha256"]
                                      for c in reg["configs"]),
        "search_discoverable": any(r["name"] == reg["workflow"] for r in
                                  server.api("GET", "/api/workflows/search?q=" + reg["workflow"])["results"]),
        "execution_listed": any(r["id"] == job["execution_id"] and r["workflow_name"] == reg["workflow"]
                                for r in server.api("GET", "/api/workflows?limit=50")["runs"]),
    }
    artifact = Path(job["workspace"]) / "visibility.json"
    checks["deterministic_artifact"] = artifact.read_text() == '{"fixture": "product-visibility-q14-v1", "ok": true}\n'
    done = server.load(server.filename(name, "done"))
    checks["matching_receipt"] = done["execution_id"] == job["execution_id"] and done["exit"] == 0
    for key in ("workflow_url", "run_url"):
        with urllib.request.urlopen(done[key], timeout=30) as response:
            checks[key + "_http200"] = response.status == 200
    public_base = "https://temper-dev.wai2shine.com"
    with urllib.request.urlopen(public_base + "/api/workflows/" + job["execution_id"], timeout=30) as response:
        public_status = json.load(response)
    checks["public_ui_api_same_execution"] = (public_status["id"] == job["execution_id"]
                                             and public_status["status"] == "completed"
                                             and public_status["workflow_name"] == job["workflow"])
    before = server.load(RESULTS / "before-integrity.json")
    checks["frozen_unchanged"] = before["frozen"] == hashes()
    checks["credentials_unchanged"] = before["credential_file_hash"] == hashlib.sha256((Path.home() / "temper-ai/.env").read_bytes()).hexdigest()
    current = registrations()
    changed = [key for key, value in before["registrations"].items()
               if current.get(key, {}).get("content") != value["content"]
               or (value["content"].startswith("unreadable:") and current.get(key, {}).get("metadata") != value["metadata"])]
    metadata_only = [key for key, value in before["registrations"].items()
                     if current.get(key, {}).get("content") == value["content"]
                     and current.get(key, {}).get("metadata") != value["metadata"]]
    added = [key for key in current if key not in before["registrations"]]
    checks["unrelated_registrations_unchanged"] = not changed and not added
    result = {"verified": server.now(), "checks": checks, "status": status, "receipt": done,
              "artifact": {"path": str(artifact), "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()},
              "changed_unrelated_names": changed, "added_unrelated_names": added,
              "registration_metadata_only_update_count": len(metadata_only),
              "unreadable_preexisting_names": [name for name, value in current.items()
                                                if value["content"].startswith("unreadable:")],
              "all_pass": all(checks.values())}
    target = RESULTS / "smoke-evidence.json"
    if target.exists() and not server.load(target).get("all_pass"):
        server.save(RESULTS / "smoke-evidence-broad-comparison.json", server.load(target))
    server.save(target, result)
    print(json.dumps(result, indent=2))
    return 0 if result["all_pass"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["baseline", "verify"])
    parser.add_argument("--name")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.phase == "baseline":
        baseline()
    else:
        raise SystemExit(verify(args.name, args.receipt))
