"""Stage tests for scripts/select_tests.py and scripts/dependency_graph.py.

Systems #67: temper-ai's pre-commit hook and GitHub CI share one test selector.
Known-answer cases:
- docs-only: an unreferenced doc runs no Python test, no frontend and no e2e; a doc a test
  reads runs only that test
- single-module change: an engine module runs its package tests and what imports or monkeypatches
  it, without fanning out through tests/conftest.py or tests/pgtier.py to unrelated tests
- config and fixture data: YAML `agent:`/`ref:`/`workflow:` keys and script paths reach their
  tests, while YAML comments, prompts (`system_prompt`, `task_template`, `description`) and
  mentions inside JSON data files do not create false edges; an engine module naming a config
  reaches that engine package's tests without pulling in every importer of the engine module;
  a fixture JSON under tests/<folder>/ runs that folder's tests and nearest basename readers
- full-suite triggers: pyproject.toml, uv.lock, tests/conftest.py, tests/pgtier.py,
  tests/machine_slot.py, scripts/git-hooks/pre-commit, .github/workflows/ci.yml, the selector
  and its rules
- frontend and e2e: frontend/** runs frontend + e2e (and only Python tests that read that
  frontend path); scripts/e2e_static_server.py runs e2e + its Python test
- unknown path, empty diff, unresolvable diff: fail safe -> everything
- batch union: several commits or files combine their selected sets; one full-trigger file in
  a batch upgrades the batch to everything
- deleted file: tests or modules that still import or name the deleted path are selected; a hub
  naming a deleted path runs everything
- CLI and formats: --staged (reads from the index), --base/--head (merge-base), --files,
  --format lines|json|pytest, --github-output, --explain; bad TOML or bad commit exits 2
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import dependency_graph as dg  # noqa: E402
import select_tests as st  # noqa: E402

RULES = st.load_rules((ROOT / st.RULES_PATH).read_text())


# A miniature temper-ai tree with the real shapes that matter: two engine packages, two test
# folders, a root conftest hub that imports both packages, a subfolder conftest, configs with
# prompts and comments, fixture JSON files, docs and frontend files.
TREE: dict[str, str] = {
    "scripts/test-selection.toml": (ROOT / st.RULES_PATH).read_text(),
    "pyproject.toml": "[project]\nname = 'temper-ai'\n",
    "uv.lock": "version = 1\n",
    "README.md": "# temper\n",
    "docs/guide.md": "Nothing reads this guide.\n",
    "docs/departments.md": "| backend_dev | Backend |\n",
    "frontend/src/App.tsx": "export const App = () => null;\n",
    "frontend/public/fonts/Inter.ttf": "font",
    "scripts/e2e_static_server.py": "PORT = 4173\n",
    "scripts/roamee_reader.py": "def read_roamee():\n    return 'ok'\n",
    "temper_ai/__init__.py": "",
    "temper_ai/tools/__init__.py": "from .web_fetch import fetch\n",
    "temper_ai/tools/web_fetch.py": "from ..shared import clock\n\ndef fetch():\n    return clock.now()\n",
    "temper_ai/tools/unused.py": "X = 1\n",
    "temper_ai/shared/__init__.py": "",
    "temper_ai/shared/clock.py": "def now():\n    return 0\n",
    "temper_ai/mcp/__init__.py": "",
    "temper_ai/mcp/server.py": "def serve():\n    return 'mcp'\n",
    "temper_ai/spawner/__init__.py": "",
    "temper_ai/spawner/box_profile.py": (
        "ACCESS = 'configs/slack/access.yaml'\n"
        "def profile():\n    return ACCESS\n"
    ),
    "temper_ai/api/__init__.py": "",
    "temper_ai/api/routes.py": "from temper_ai.spawner import box_profile\n",
    "configs/slack/access.yaml": "workflows: [github_work]\n",
    "configs/agents/backend_dev.yaml": (
        "# Mentions docs/guide.md and docker-compose.yml in a comment.\n"
        "agent:\n"
        "  name: backend_dev\n"
        "  type: llm\n"
        "  description: >\n"
        "    Reads docs/guide.md and temper_ai/mcp/server.py in prose only.\n"
        "  system_prompt: |\n"
        "    Never touch docs/guide.md or temper_ai/mcp/server.py.\n"
    ),
    "configs/workflows/build.yaml": (
        "workflow:\n"
        "  name: build\n"
        "  nodes:\n"
        "    code:\n"
        "      agent: backend_dev\n"
    ),
    "configs/epd/bin/leftovers.py": "def audit():\n    return []\n",
    "configs/design/recorded/source.json": (
        '{"note": "mentions temper_ai/mcp/server.py and configs/epd/bin/leftovers.py as plain data"}'
    ),
    "tests/__init__.py": "",
    "tests/conftest.py": (
        "import temper_ai.tools.web_fetch\n"
        "import temper_ai.mcp.server\n"
        "import temper_ai.api.routes\n"
    ),
    "tests/pgtier.py": "import temper_ai.shared.clock\n",
    "tests/machine_slot.py": "MARKER = 'TEMPER_PYTEST_MACHINE_SLOT'\n",
    "tests/test_tools/test_web_fetch.py": (
        "from temper_ai.tools import web_fetch\n"
        "def test_fetch():\n    assert web_fetch.fetch() == 0\n"
    ),
    "tests/test_tools/test_monkeypatch.py": (
        "def test_patched(monkeypatch):\n"
        "    monkeypatch.setattr('temper_ai.tools.web_fetch.fetch', lambda: 1)\n"
    ),
    "tests/test_mcp/test_server.py": (
        "from temper_ai.mcp.server import serve\n"
        "def test_serve():\n    assert serve() == 'mcp'\n"
    ),
    "tests/test_mcp/fixtures/sample.json": '{"kind": "mcp"}',
    "tests/test_api/conftest.py": "import temper_ai.api.routes\n",
    "tests/test_api/test_routes.py": "def test_routes():\n    assert True\n",
    "tests/test_api/test_fonts.py": (
        "from pathlib import Path\n"
        "FONTS = Path('frontend/public/fonts')\n"
        "def test_fonts():\n    assert FONTS.name == 'fonts'\n"
    ),
    "tests/test_spawner/test_box_profile.py": (
        "from temper_ai.spawner import box_profile\n"
        "def test_profile():\n    assert box_profile.profile()\n"
    ),
    "tests/test_epd/test_departments_doc.py": (
        "from pathlib import Path\n"
        "DOC = Path('docs') / 'departments.md'\n"
        "def test_doc():\n    assert DOC.name == 'departments.md'\n"
    ),
    "tests/test_epd/test_build_workflow.py": (
        "from pathlib import Path\n"
        "WF = Path('configs/workflows/build.yaml')\n"
        "def test_wf():\n    assert WF.name == 'build.yaml'\n"
    ),
    "tests/test_epd/test_leftovers.py": (
        "import importlib\n"
        "mod = importlib.import_module('leftovers')\n"
        "def test_audit():\n    assert mod.audit() == []\n"
    ),
    "tests/test_ci/test_e2e_server.py": (
        "from pathlib import Path\n"
        "SERVER = Path('../scripts/e2e_static_server.py')\n"
        "def test_server():\n    assert SERVER.name.endswith('.py')\n"
    ),
    "tests/test_scripts/test_roamee.py": (
        "from scripts import roamee_reader\n"
        "def test_roamee():\n    assert roamee_reader.read_roamee() == 'ok'\n"
    ),
}


def _select(changes: list[st.Change], tree: dict[str, str] = TREE) -> st.Selection:
    readable = [p for p in tree if dg.should_read(p)]
    refs = dg.read_references(readable, tree.get)
    return st.select(changes, RULES, tree, lambda: dg.build_graph(tree, refs))


def test_docs_and_single_module_and_config_selection():
    # 1. Docs-only: an unreferenced doc runs no Python tests, no frontend and no e2e;
    #    a doc read by a test runs only that test.
    unreferenced = _select([st.Change("docs/guide.md")])
    assert unreferenced.python == "none"
    assert unreferenced.pytest_targets() == []
    assert not unreferenced.frontend and not unreferenced.e2e

    referenced_doc = _select([st.Change("docs/departments.md")])
    assert referenced_doc.python == "some"
    assert referenced_doc.tests == {"tests/test_epd/test_departments_doc.py"}
    assert not referenced_doc.frontend and not referenced_doc.e2e

    # 2. Single-module change: reaches direct importers, monkeypatch targets and package tests,
    #    and stops at tests/conftest.py and tests/pgtier.py instead of pulling in test_mcp or test_api.
    web_fetch = _select([st.Change("temper_ai/tools/web_fetch.py")])
    assert web_fetch.python == "some"
    assert web_fetch.tests == {
        "tests/test_tools/test_web_fetch.py",
        "tests/test_tools/test_monkeypatch.py",
    }
    assert "tests/test_mcp/test_server.py" not in web_fetch.tests

    # Shared module imported via relative import (`from ..shared import clock`) reaches web_fetch's tests.
    clock = _select([st.Change("temper_ai/shared/clock.py")])
    assert clock.tests == {
        "tests/test_tools/test_web_fetch.py",
        "tests/test_tools/test_monkeypatch.py",
    }

    # Subfolder conftest reaches every test in its own folder only.
    api_conftest = _select([st.Change("tests/test_api/conftest.py")])
    assert api_conftest.tests == {"tests/test_api/test_routes.py", "tests/test_api/test_fonts.py"}

    # 3. Config YAML: `agent: backend_dev` in build.yaml links backend_dev.yaml -> build.yaml -> test,
    #    while comments and prose in backend_dev.yaml do not link docs/guide.md or mcp/server.py.
    agent_yaml = _select([st.Change("configs/agents/backend_dev.yaml")])
    assert agent_yaml.tests == {"tests/test_epd/test_build_workflow.py"}

    # JSON data file is a leaf: mentions inside it do not make mcp/server.py or leftovers.py reach it.
    mcp = _select([st.Change("temper_ai/mcp/server.py")])
    assert mcp.tests == {"tests/test_mcp/test_server.py"}
    leftovers = _select([st.Change("configs/epd/bin/leftovers.py")])
    assert "tests/test_epd/test_leftovers.py" in leftovers.tests
    assert "tests/test_mcp/test_server.py" not in leftovers.tests

    # Engine module naming a non-engine config reaches that engine package's tests (one hop),
    # not every test that imports temper_ai/api/routes.py.
    slack_access = _select([st.Change("configs/slack/access.yaml")])
    assert slack_access.tests == {"tests/test_spawner/test_box_profile.py"}
    assert "tests/test_api/test_routes.py" not in slack_access.tests

    # 4. Fixture JSON in a test folder runs that folder's tests.
    fixture_json = _select([st.Change("tests/test_mcp/fixtures/sample.json")])
    assert fixture_json.tests == {"tests/test_mcp/test_server.py"}

    # 5. Frontend and e2e plumbing.
    tsx = _select([st.Change("frontend/src/App.tsx")])
    assert tsx.python == "none" and tsx.frontend and tsx.e2e

    font = _select([st.Change("frontend/public/fonts/Inter.ttf")])
    assert font.tests == {"tests/test_api/test_fonts.py"} and font.frontend and font.e2e

    e2e_server = _select([st.Change("scripts/e2e_static_server.py")])
    assert e2e_server.tests == {"tests/test_ci/test_e2e_server.py"}
    assert e2e_server.e2e and not e2e_server.frontend


@pytest.mark.parametrize("trigger", [
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    "tests/conftest.py",
    "tests/pgtier.py",
    "tests/machine_slot.py",
    "tests/__init__.py",
    "scripts/select_tests.py",
    "scripts/dependency_graph.py",
    "scripts/test-selection.toml",
    "scripts/git-hooks/pre-commit",
    "scripts/test-postgres.sh",
    ".github/workflows/ci.yml",
    ".github/workflows/nightly.yml",
    "mystery/unlisted_file.bin",
    "new_root_file.xyz",
])
def test_full_suite_triggers_and_unknown_paths_run_everything(trigger: str):
    sel = _select([st.Change(trigger)])
    assert sel.everything and sel.python == "all" and sel.frontend and sel.e2e
    assert sel.pytest_targets() == ["tests/"]


def test_empty_diff_batch_union_and_deleted_files():
    # Empty diff runs everything.
    empty = _select([])
    assert empty.everything and empty.python == "all" and empty.frontend and empty.e2e

    # Batch union combines python tests and flags from each changed file.
    batch = _select([
        st.Change("docs/departments.md"),
        st.Change("frontend/src/App.tsx"),
        st.Change("scripts/roamee_reader.py"),
    ])
    assert not batch.everything
    assert batch.tests == {
        "tests/test_epd/test_departments_doc.py",
        "tests/test_scripts/test_roamee.py",
    }
    assert batch.frontend and batch.e2e

    # One full-suite trigger in a batch upgrades the whole batch to everything.
    upgraded = _select([st.Change("docs/guide.md"), st.Change("pyproject.toml")])
    assert upgraded.everything and upgraded.python == "all"

    # Deleted file: tests or modules that still import or name it are selected.
    without_roamee = {k: v for k, v in TREE.items() if k != "scripts/roamee_reader.py"}
    deleted_script = _select([st.Change("scripts/roamee_reader.py", deleted=True)], without_roamee)
    assert not deleted_script.everything
    assert deleted_script.tests == {"tests/test_scripts/test_roamee.py"}

    # Deleted file still imported by a hub (tests/conftest.py) runs everything.
    without_mcp = {k: v for k, v in TREE.items() if k != "temper_ai/mcp/server.py"}
    deleted_hub_dep = _select([st.Change("temper_ai/mcp/server.py", deleted=True)], without_mcp)
    assert deleted_hub_dep.everything


def test_git_modes_cli_outputs_and_error_exits(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    git("init", "-q", "-b", "master")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    for rel, content in TREE.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    git("add", ".")
    git("commit", "-q", "-m", "initial")

    # Branch with two commits (batch union across merge-base..HEAD).
    git("checkout", "-q", "-b", "feature")
    (repo / "docs/departments.md").write_text("| backend_dev | Updated |\n")
    git("add", "docs/departments.md")
    git("commit", "-q", "-m", "doc edit")
    (repo / "frontend/src/App.tsx").write_text("export const App = () => 'hi';\n")
    git("add", "frontend/src/App.tsx")
    git("commit", "-q", "-m", "fe edit")

    gh_out = tmp_path / "github_output.txt"
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts/select_tests.py"),
         "--repo", str(repo), "--base", "master", "--head", "HEAD",
         "--explain", "--format", "json", "--github-output", str(gh_out)],
        capture_output=True, text=True, check=False,
    )
    assert done.returncode == 0, done.stderr
    payload = json.loads(done.stdout)
    assert payload["python"] == "some"
    assert payload["python_tests"] == ["tests/test_epd/test_departments_doc.py"]
    assert payload["frontend"] is True and payload["e2e"] is True
    assert "select_tests: base" in done.stderr
    assert gh_out.read_text().splitlines() == [
        "python=some",
        "python_tests=tests/test_epd/test_departments_doc.py",
        "frontend=true",
        "e2e=true",
    ]

    # --staged reads the index, not HEAD or the working tree.
    git("checkout", "-q", "master")
    (repo / "scripts/roamee_reader.py").write_text("def read_roamee():\n    return 'staged'\n")
    git("add", "scripts/roamee_reader.py")
    # Unstaged edit to pyproject.toml must NOT trigger everything when --staged is used.
    (repo / "pyproject.toml").write_text("[project]\nname = 'unstaged'\n")
    staged = subprocess.run(
        [sys.executable, str(ROOT / "scripts/select_tests.py"),
         "--repo", str(repo), "--staged", "--format", "pytest"],
        capture_output=True, text=True, check=False,
    )
    assert staged.returncode == 0, staged.stderr
    assert staged.stdout.splitlines() == ["tests/test_scripts/test_roamee.py"]

    # Bad commit ref or broken TOML rules fail loudly with exit code 2.
    bad_ref = subprocess.run(
        [sys.executable, str(ROOT / "scripts/select_tests.py"),
         "--repo", str(repo), "--head", "no-such-commit"],
        capture_output=True, text=True, check=False,
    )
    assert bad_ref.returncode == 2

    bad_rules = tmp_path / "bad.toml"
    bad_rules.write_text("version = 99\n")
    bad_toml = subprocess.run(
        [sys.executable, str(ROOT / "scripts/select_tests.py"),
         "--repo", str(repo), "--rules", str(bad_rules)],
        capture_output=True, text=True, check=False,
    )
    assert bad_toml.returncode == 2


def test_live_repo_hook_ci_and_heavy_tier_wiring():
    # Pre-commit hook syntax and selector / heavy-marker wiring.
    hook = ROOT / "scripts/git-hooks/pre-commit"
    syntax = subprocess.run(["bash", "-n", str(hook)], capture_output=True, text=True, check=False)
    assert syntax.returncode == 0, syntax.stderr
    hook_text = hook.read_text()
    assert "scripts/select_tests.py" in hook_text
    assert '-m "not heavy"' in hook_text

    # GitHub CI workflow wires test, test-postgres, frontend and e2e to select,
    # excludes heavy tests from the per-commit gate, and nightly runs full-and-heavy.
    ci_text = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "scripts/select_tests.py" in ci_text
    assert "needs: select" in ci_text
    assert '-m "not heavy"' in ci_text

    nightly_text = (ROOT / ".github/workflows/nightly.yml").read_text()
    assert "full-and-heavy:" in nightly_text
    assert "uv run pytest tests/ --timeout=240 -n auto --junitxml=junit-full.xml" in nightly_text

    # Heavy marker is registered in pyproject.toml and applied to the seven heavy sweep files.
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert '"heavy:' in pyproject
    for rel in (
        "tests/test_observability/test_usage_reconcile.py",
        "tests/test_runner/pi_team/test_flow_team.py",
        "tests/test_runner/test_reaper_effect_generation.py",
        "tests/test_runner/test_reaper_generation.py",
        "tests/test_runner/test_row_generation.py",
        "tests/test_runner/test_writer_scan.py",
        "tests/test_spawner/test_docker_spawner.py",
    ):
        assert "@pytest.mark.heavy" in (ROOT / rel).read_text(), rel

