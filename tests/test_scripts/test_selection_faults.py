"""Execute clean controls and injected faults for every selector rule, offline.

These are miniature repositories, not claims that historical failures were rerun.
Each control must pass before its single changed file is corrupted. The selected
pytest target must then report the named probe failed, not a collection error.
No application/model/browser server is started.
"""
from __future__ import annotations

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.test_scripts.test_select_tests import RULES, _select, st


@dataclass(frozen=True)
class Fault:
    rule: str
    changed: str
    test: str = "tests/test_probe.py"
    references_path: bool = False
    frontend: bool = False
    e2e: bool = False


FAULTS = (
    Fault("selection", "scripts/select_tests.py", frontend=True, e2e=True),
    Fault("dependencies", "pyproject.toml", frontend=True, e2e=True),
    Fault("test hubs", "tests/machine_slot.py", frontend=True, e2e=True),
    Fault("pure host contracts", "docs/p3-host-contracts.md", "tests/test_p3_host_contracts/test_probe.py"),
    Fault("test file", "tests/test_probe.py"),
    Fault("test plumbing and data", "tests/test_group/sample.json", "tests/test_group/test_probe.py"),
    Fault("engine", "temper_ai/alpha/value.py", "tests/test_alpha/test_probe.py"),
    Fault("configs", "configs/agents/selected_agent.yaml"),
    Fault("browser test plumbing", "scripts/e2e_static_server.py", references_path=True, e2e=True),
    Fault("scripts", "scripts/check_value.py", references_path=True),
    Fault("frontend", "frontend/probe.js", references_path=True, frontend=True, e2e=True),
    Fault("docs and project files", "docs/probe.md", references_path=True),
    Fault("unknown", "unknown/probe.bin", frontend=True, e2e=True),
)


def _tree(fault: Fault) -> dict[str, str]:
    # Environment lookup deliberately supplies no dependency edge. Full/package/
    # folder rules must work independently of the literal-reference rule.
    expression = repr(fault.changed) if fault.references_path else "os.environ['RULE_PROBE_PATH']"
    probe = ("import os\nfrom pathlib import Path\n"
             f"def test_rule_probe():\n    assert Path({expression}).read_text().strip() == 'good'\n")
    if fault.rule == "test file":
        probe = "def test_rule_probe():\n    assert 'good' == 'good'\n"
    if fault.rule == "configs":
        probe = "from pathlib import Path\nWORKFLOW = Path('configs/workflows/use.yaml')\n" + probe
    tree = {
        "pytest.ini": "[pytest]\n",
        "tests/conftest.py": "",
        "tests/test_clean.py": "def test_clean():\n    assert True\n",
        fault.changed: "good\n",
        fault.test: probe,
    }
    if fault.rule == "configs":
        tree["configs/workflows/use.yaml"] = "agent: selected_agent\n"
    if fault.rule == "pure host contracts":
        tree["p3_host_contracts/__init__.py"] = ""
    return tree


def _run(repo: Path, targets: list[str], changed: str) -> tuple[int | None, dict[str, str]]:
    if not targets:
        return None, {}
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", RULE_PROBE_PATH=changed, PYTHONPATH=str(repo))
    env.pop("PYTEST_ADDOPTS", None)
    report = repo / "probe-results.xml"
    try:
        result = subprocess.run([sys.executable, "-m", "pytest", "-c", "pytest.ini", *targets,
                                 "-q", "--junitxml", str(report)], cwd=repo, env=env,
                                capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None, {}  # never put child argv or streams in pytest failure text
    cases: dict[str, str] = {}
    if report.exists():
        for case in ET.parse(report).iter("testcase"):
            state = "failed" if case.find("failure") is not None else "passed"
            if case.find("error") is not None:
                state = "error"
            cases[case.attrib["name"]] = state
    return result.returncode, cases


def test_fault_inventory_covers_every_rule():
    assert {fault.rule for fault in FAULTS} == {rule.name for rule in RULES.rules} | {"unknown"}
    assert len(FAULTS) >= 8


@pytest.mark.parametrize("fault", FAULTS, ids=lambda fault: fault.rule)
def test_selected_checks_catch_injected_fault_after_clean_control(tmp_path: Path, fault: Fault):
    tree = _tree(fault)
    for path, text in tree.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    selected = _select([st.Change(fault.changed)], tree)
    assert selected.frontend is fault.frontend
    assert selected.e2e is fault.e2e
    targets = selected.pytest_targets()
    control_exit, control_cases = _run(tmp_path, targets, fault.changed)
    assert control_exit == 0
    assert control_cases.get("test_rule_probe") == "passed"

    original = tree[fault.changed]
    changed = original.replace("assert 'good' == 'good'", "assert 'bad' == 'good'") if fault.rule == "test file" else "bad\n"
    (tmp_path / fault.changed).write_text(changed)
    tree[fault.changed] = changed
    selected_after = _select([st.Change(fault.changed)], tree)
    fault_exit, fault_cases = _run(tmp_path, selected_after.pytest_targets(), fault.changed)
    assert fault_exit == 1
    assert fault_cases.get("test_rule_probe") == "failed"
    assert "error" not in fault_cases.values()


@dataclass(frozen=True)
class MechanismFault:
    mechanism: str
    changed: str
    probe_test: str
    extra_files: dict[str, str]
    clean_content: str
    fault_content: str
    expect_everything: bool = False


MECHANISM_FAULTS: tuple[MechanismFault, ...] = (
    MechanismFault(
        mechanism="dynamic_import_by_name",
        changed="configs/epd/bin/kb_refresh.py",
        probe_test="tests/test_epd/test_kb_refresh.py",
        extra_files={
            "tests/test_epd/test_kb_refresh.py": (
                "import importlib, sys\n"
                "from pathlib import Path\n"
                "sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'configs/epd/bin'))\n"
                "def test_mechanism_probe():\n"
                "    mod = importlib.import_module('kb_refresh')\n"
                "    assert mod.status() == 'ok'\n"
            ),
        },
        clean_content="def status():\n    return 'ok'\n",
        fault_content="def status():\n    return 'broken'\n",
    ),
    MechanismFault(
        mechanism="monkeypatch_dotted_string",
        changed="temper_ai/tools/web_fetch.py",
        probe_test="tests/test_agent/test_monkeypatch_fetch.py",
        extra_files={
            "temper_ai/__init__.py": "",
            "temper_ai/tools/__init__.py": "",
            "tests/test_agent/test_monkeypatch_fetch.py": (
                "import importlib\n"
                "TARGET = 'temper_ai.tools.web_fetch.DEFAULT_TIMEOUT'\n"
                "def test_mechanism_probe(monkeypatch):\n"
                "    mod_name, attr = TARGET.rsplit('.', 1)\n"
                "    mod = importlib.import_module(mod_name)\n"
                "    assert getattr(mod, attr) == 30\n"
            ),
        },
        clean_content="DEFAULT_TIMEOUT = 30\n",
        fault_content="DEFAULT_TIMEOUT = 5\n",
    ),
    MechanismFault(
        mechanism="fixture_chain_through_conftest",
        changed="temper_ai/helpers/token_helper.py",
        probe_test="tests/test_agent/test_fixture_chain.py",
        extra_files={
            "temper_ai/__init__.py": "",
            "temper_ai/helpers/__init__.py": "",
            "tests/conftest.py": (
                "import pytest\n"
                "@pytest.fixture\n"
                "def base_token():\n"
                "    from temper_ai.helpers.token_helper import make_token\n"
                "    return make_token()\n"
                "@pytest.fixture\n"
                "def wrapped_token(base_token):\n"
                "    return f'wrapped:{base_token}'\n"
            ),
            "tests/test_agent/test_fixture_chain.py": (
                "def test_mechanism_probe(wrapped_token):\n"
                "    assert wrapped_token == 'wrapped:valid'\n"
            ),
        },
        clean_content="def make_token():\n    return 'valid'\n",
        fault_content="def make_token():\n    return 'expired'\n",
    ),
    MechanismFault(
        mechanism="config_yaml_agent_reference",
        changed="configs/agents/fact_checker.yaml",
        probe_test="tests/test_workflows/test_fact_pipeline.py",
        extra_files={
            "configs/workflows/fact_pipeline.yaml": (
                "name: fact_pipeline\n"
                "steps:\n"
                "  - id: verify\n"
                "    agent: fact_checker\n"
            ),
            "tests/test_workflows/test_fact_pipeline.py": (
                "from pathlib import Path\n"
                "WF = Path('configs/workflows/fact_pipeline.yaml')\n"
                "AG = Path('configs/agents/fact_checker.yaml')\n"
                "def test_mechanism_probe():\n"
                "    assert WF.exists() and 'model: gpt-5' in AG.read_text()\n"
            ),
        },
        clean_content="name: fact_checker\nmodel: gpt-5\n",
        fault_content="name: fact_checker\nmodel: broken-model\n",
    ),
    MechanismFault(
        mechanism="folder_reader_path_join",
        changed="tests/fixtures/cards/card_a.json",
        probe_test="tests/test_epd/test_cards_folder.py",
        extra_files={
            "tests/test_epd/test_cards_folder.py": (
                "from pathlib import Path\n"
                "CARDS = Path('tests') / 'fixtures' / 'cards'\n"
                "def test_mechanism_probe():\n"
                "    for p in CARDS.glob('*.json'):\n"
                "        assert p.read_text().strip() == '{\"ok\": true}'\n"
            ),
        },
        clean_content='{"ok": true}\n',
        fault_content='{"ok": false}\n',
    ),
    MechanismFault(
        mechanism="subprocess_cli_script_path",
        changed="scripts/check_version_banner.py",
        probe_test="tests/test_scripts/test_version_banner.py",
        extra_files={
            "tests/test_scripts/test_version_banner.py": (
                "import subprocess, sys\n"
                "def test_mechanism_probe():\n"
                "    res = subprocess.run([sys.executable, 'scripts/check_version_banner.py'], capture_output=True, text=True)\n"
                "    assert res.returncode == 0 and res.stdout.strip() == 'banner-ok'\n"
            ),
        },
        clean_content="print('banner-ok')\n",
        fault_content="import sys; sys.exit(1)\n",
    ),
    MechanismFault(
        mechanism="sql_file_read_by_db_module",
        changed="scripts/sql/schema_check.sql",
        probe_test="tests/test_database/test_schema_sql.py",
        extra_files={
            "temper_ai/__init__.py": "",
            "temper_ai/database/__init__.py": "",
            "temper_ai/database/migrations.py": (
                "from pathlib import Path\n"
                "SQL_PATH = Path('scripts/sql/schema_check.sql')\n"
                "def load_sql() -> str:\n"
                "    return SQL_PATH.read_text().strip()\n"
            ),
            "tests/test_database/test_schema_sql.py": (
                "from temper_ai.database.migrations import load_sql\n"
                "def test_mechanism_probe():\n"
                "    assert load_sql() == 'SELECT 1;'\n"
            ),
        },
        clean_content="SELECT 1;\n",
        fault_content="SELECT BROKEN;\n",
    ),
)


@pytest.mark.parametrize("mf", MECHANISM_FAULTS, ids=[m.mechanism for m in MECHANISM_FAULTS])
def test_each_dependency_mechanism_catches_injected_fault(mf: MechanismFault, tmp_path: Path):
    tree: dict[str, str] = {
        "pytest.ini": "[pytest]\npythonpath = .\n",
        "tests/conftest.py": "import pytest\n",
        "tests/test_unrelated.py": "def test_unrelated():\n    assert 1 == 1\n",
        **mf.extra_files,
        mf.changed: mf.clean_content,
    }
    for path, text in tree.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    sel_clean = _select([st.Change(mf.changed)], tree)
    assert sel_clean.everything is mf.expect_everything
    assert mf.probe_test in sel_clean.tests or sel_clean.everything
    if not mf.expect_everything:
        assert "tests/test_unrelated.py" not in sel_clean.tests
    clean_exit, clean_cases = _run(tmp_path, sel_clean.pytest_targets(), mf.changed)
    assert clean_exit == 0
    assert clean_cases.get("test_mechanism_probe") == "passed"

    (tmp_path / mf.changed).write_text(mf.fault_content)
    tree[mf.changed] = mf.fault_content
    sel_fault = _select([st.Change(mf.changed)], tree)
    fault_exit, fault_cases = _run(tmp_path, sel_fault.pytest_targets(), mf.changed)
    assert fault_exit == 1
    assert fault_cases.get("test_mechanism_probe") == "failed"
    assert "error" not in fault_cases.values()

