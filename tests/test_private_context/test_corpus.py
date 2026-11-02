"""Validate shared selectors and reporter, not nonexistent service behavior."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from temper_ai.private_context.private_json import encode_private
from temper_ai.private_context.wire import decode_registration, decode_wire

from . import ipd1
from .ipd1 import require


def test_m1_to_m8_each_have_one_changed_arrangement_and_fixed_safe_expectations() -> None:
    manifest = ipd1.manifest()
    rows = {row.id: row for row in manifest.cases}
    require(len(rows) == len(manifest.cases) == 16)
    for number in range(1, 9):
        good = rows[f"M{number}-good"]
        bad = rows[f"M{number}-refusal"]
        require(good.pair_id == bad.id and bad.pair_id == good.id)
        left = good.arrange.model_dump()
        right = bad.arrange.model_dump()
        require(sum(left[key] != right[key] for key in left) == 1)
        require(good.act == bad.act and good.expect != bad.expect)
        for row in (good, bad):
            context = decode_registration(ipd1.registration(row.arrange.media_fixture).to_private_json())
            ipd1.schemas().validate_registration(context)
    require(ipd1.scan({ipd1.Surface.EXPORT: manifest.model_dump_json()}).clean)
    # These counts are expected specs; report *only* the contracts checked here.
    report = ipd1.SafeReport(case_id="M1-good", stage="contracts", passed=True, checks=16)
    require(ipd1.scan({ipd1.Surface.EXPORT: ipd1.safe_json(report)}).clean)


@pytest.mark.parametrize("surface", list(ipd1.Surface), ids=lambda surface: surface.value)
@pytest.mark.parametrize("placement", ["plain", "allowed-prefix", "allowed-suffix", "nested", "extra-line"])
def test_scanner_catches_leaks_in_all_shapes_and_never_returns_bytes(surface: ipd1.Surface, placement: str) -> None:
    marker = ipd1.canaries()[0]
    content = {"plain": marker, "allowed-prefix": b"READY " + marker, "allowed-suffix": marker + b" entered", "nested": json.dumps({"safe": {"text": marker.decode()}}).encode(), "extra-line": b"READY\n" + marker}[placement]
    scan = ipd1.scan({surface: content})
    require(not scan.clean and scan.leak_count > 0)
    encoded = ipd1.safe_json(scan).encode()
    require(all(needle not in encoded for needle in ipd1.canaries()))
    require(ipd1.scan({surface: b"READY\nentered\n"}).clean)


@pytest.mark.parametrize("index", range(6))
def test_independent_text_draft_key_provider_png_and_base64_markers(index: int) -> None:
    report = ipd1.scan({ipd1.Surface.ERROR: ipd1.canaries()[index]})
    require(not report.clean and report.leak_count >= 1)


def test_fixture_reports_are_closed_and_do_not_accept_arbitrary_prose() -> None:
    from .test_contracts import refused
    for field, value in (("case_id", "M1-good private suffix"), ("stage", "actual-inkflow"), ("extra", "raw"), ("code", "raw"), ("checks", True)):
        obj = {"suite": "IPD-1", "case_id": "M1-good", "stage": "contracts", "passed": True}
        obj[field] = value
        refused(lambda: decode_wire(encode_private(obj), ipd1.SafeReport))
    with pytest.raises(AssertionError, match="^invalid safe check$"):
        ipd1.require(False, "private text")  # type: ignore[arg-type]


def child_result(command: list[str], env: dict[str, str]) -> tuple[int, bytes]:
    # Keep the CompletedProcess repr and TimeoutExpired.argv/stdout off failures.
    try:
        proc = subprocess.run(command, capture_output=True, env=env, timeout=60)
    except (OSError, subprocess.SubprocessError):
        pass
    else:
        return proc.returncode, proc.stdout + proc.stderr
    raise AssertionError("child did not finish")


@pytest.mark.parametrize("mutant", [False, True], ids=["safe-failure", "leaking-negative-control"])
def test_verbose_and_junit_failure_text_canary(tmp_path: Path, mutant: bool) -> None:
    # Child stores synthetic bodies locally. Its output is scanned here, never
    # asserted directly or returned as exception detail. -vv defeats truncation.
    target = tmp_path / "test_canary.py"
    target.write_text(
        "from tests.test_private_context import ipd1\n"
        "def test_failure():\n"
        "    private = ipd1.canaries()[0].decode()\n"
        + ("    assert 'READY ' + private == 'READY'\n" if mutant else "    ipd1.require(private == 'READY', ipd1.CheckCode.EXPECTATION)\n"),
        encoding="utf-8",
    )
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n", encoding="utf-8")
    junit = tmp_path / "report.xml"
    env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONPATH": str(Path(__file__).resolve().parents[2].parent)}
    code, output = child_result([sys.executable, "-m", "pytest", "-c", str(config), "-vv", "--tb=short", f"--junitxml={junit}", str(target)], env)
    require(code == 1)
    report = ipd1.scan({ipd1.Surface.ERROR: output, ipd1.Surface.EXPORT: junit.read_bytes()})
    require(report.clean is not mutant)
    require(report.inspected == 2)
