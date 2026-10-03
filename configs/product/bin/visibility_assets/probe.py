#!/usr/bin/env python3
"""Deterministic Product smoke asset: no network, models, credentials or research."""
import argparse
import json
from pathlib import Path

EXPECTED = {"fixture": "product-visibility-q14-v1", "ok": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--operation", choices=["prepare", "write", "check"], required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--execution-id", required=True)
    args = parser.parse_args()
    fixture = Path(__file__).with_name("fixture.txt").read_text().strip()
    assert fixture == EXPECTED["fixture"], "staged fixture mismatch"
    assert args.workspace.is_dir(), "workspace missing inside worker"
    artifact = args.workspace / "visibility.json"
    if args.operation == "write":
        with artifact.open("x") as output:
            output.write(json.dumps(EXPECTED, sort_keys=True) + "\n")
    if args.operation == "check":
        assert artifact.read_text() == json.dumps(EXPECTED, sort_keys=True) + "\n", "artifact mismatch"
    print(json.dumps({"ok": True, "operation": args.operation, "execution_id": args.execution_id,
                      "artifact_path": str(artifact), "workspace": str(args.workspace)}))


if __name__ == "__main__":
    main()
