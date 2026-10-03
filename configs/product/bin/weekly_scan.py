#!/usr/bin/env python3
"""Existing Monday Product cadence, now shared-server only; no local CLI fallback."""
import datetime as dt
import os
import shutil
import subprocess
import sys
from pathlib import Path

import server_run as server


def main() -> int:
    date = dt.datetime.now(dt.UTC).astimezone().date().isoformat()
    home = Path.home()
    cadence = Path(os.environ.get("CADENCE_DIR", home / "product-scan-cadence"))
    temper = Path(os.environ.get("TEMPER_DIR", home / "temper-ai"))
    history = Path(os.environ.get("HIST_DIR", temper / "state/scan/history"))
    daily = Path(os.environ.get("DAILY_DIR", home / ".pi/agent/memory/daily"))
    logs = Path(os.environ.get("RUN_LOG_DIR", cadence / "logs"))
    logs.mkdir(parents=True, exist_ok=True)
    logfile = logs / f"run-{date}.log"

    def log(text):
        with logfile.open("a") as out:
            out.write(f"[{server.now()}] {text}\n")
        print(text, flush=True)

    def note(text):
        daily.mkdir(parents=True, exist_ok=True)
        with (daily / f"{date}.md").open("a") as out:
            out.write(f"\n<!-- {server.now()} [scan-cadence] -->\n#product Weekly market scan: {text}\n")
        log(text)

    job = None
    if os.environ.get("SKIP_SCAN") == "1":
        source = Path(os.environ.get("SCAN_DIR", temper / "state/scan"))
        note("SKIP_SCAN=1: offline digest only, local-only archive, no shared run submitted")
    else:
        workspace = server.SHARED / f"weekly-scan-{date}"
        workspace.mkdir(parents=True, exist_ok=True)
        workflow = os.environ.get("WORKFLOW", "scan_market")
        inputs = Path(os.environ["PRODUCT_SCAN_INPUTS"]) if os.environ.get("PRODUCT_SCAN_INPUTS") else None
        try:
            # Exactly one detached monitor owns status reads/receipts. The existing
            # scheduler waits for that unit, never starts a second monitor or run.
            job = server.launch(f"weekly-scan-{date}", workflow, inputs, workspace)
            log(f"shared run submitted: {job['run_url']}")
            done_path = server.filename(job["name"], "done")
            if not done_path.exists():
                subprocess.run(["systemctl", "--user", "--wait", "start", f"product-{job['name']}.service"],
                               capture_output=True, check=False)
            if not done_path.exists():
                raise server.Refused("monitor ended without a terminal receipt; existing run stays fenced")
            rc = server.load(done_path)["exit"]
        except (server.Refused, server.APIError, OSError, ValueError) as exc:
            note(f"NO completed scan: {exc}; inspect the existing job, never replay an uncertain POST")
            return 1
        if rc:
            note(f"FAILED shared scan: {job['run_url']}; no snapshot accepted; cost/status in server receipt")
            return rc
        source = workspace / "state/scan"

    files = sorted(source.glob("*.md"))
    if not files:
        note(f"FAILED output collection: no markdown at {source}; do not substitute old state/scan outputs")
        return 1
    snapshot = history / date
    if snapshot.exists():
        note(f"REFUSED existing snapshot {snapshot}; old history is never overwritten")
        return 1
    snapshot.mkdir(parents=True)
    for file in files:
        shutil.copy2(file, snapshot / file.name)
    if job:
        receipt = server.load(server.filename(job["name"], "done"))
        server.save(snapshot / "server-run.json", receipt)
    previous = sorted(path for path in history.iterdir()
                      if path.is_dir() and path.name < date and len(path.name) == 10)
    command = [sys.executable, str(cadence / "digest.py"), "--current", str(snapshot),
               "--out", str(snapshot / "digest.md"), "--date", date]
    if previous:
        command += ["--previous", str(previous[-1])]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    if result.returncode:
        note(f"FAILED digest: snapshot preserved at {snapshot}; run {job['run_url'] if job else 'local-only'}")
        return result.returncode
    summary = result.stdout.strip()
    if job:
        with (snapshot / "digest.md").open("a") as out:
            out.write(f"\n## Shared Temper execution\nWorkflow: {job['workflow_url']}\nRun: {job['run_url']}\n"
                      f"Cost: ${receipt['cost']}\nWorkspace: {job['workspace']}\n")
        summary += f"; shared run {job['run_url']}, cost ${receipt['cost']}"
    note(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
