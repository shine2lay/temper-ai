"""Known-answer fixture graph cases: no implicit exemption for shared pytest setup."""
from __future__ import annotations

import pytest

from tests.test_scripts.test_select_tests import _select, st

MODULE = "temper_ai/alpha/source.py"
CONSUMER = "tests/test_consumers/test_uses.py"
OTHER = "tests/test_other/test_plain.py"
BASE = {
    "temper_ai/__init__.py": "",
    "temper_ai/alpha/__init__.py": "",
    MODULE: "def value():\n    return 7\n",
    "tests/__init__.py": "",
    "tests/conftest.py": "import pytest\n",
    CONSUMER: "def test_uses(resource):\n    assert resource == 7\n",
    OTHER: "def test_plain():\n    assert True\n",
}
OPTIONAL = """
@pytest.fixture
def resource():
    from temper_ai.alpha.source import value
    return value()
"""


def picked(tree: dict[str, str], changed: str = MODULE) -> set[str]:
    result = _select([st.Change(changed)], tree)
    return {p for p in tree if st.is_test_file(p)} if result.everything else result.tests


def test_requested_fixture_body_not_unused_body():
    tree = {**BASE, "tests/conftest.py": "import pytest\n" + OPTIONAL}
    assert picked(tree) == {CONSUMER}
    tree[CONSUMER] = "def test_uses():\n    assert True\n"
    assert picked(tree) == set()


def test_autouse_and_transitive_pgtier_helpers_reach_every_test():
    tree = {**BASE,
            "tests/conftest.py": """
import pytest
@pytest.fixture
def resource():
    from tests.pgtier import value
    return value()
@pytest.fixture(autouse=True)
def setup(resource):
    assert resource == 7
""",
            "tests/pgtier.py": "from temper_ai.alpha.source import value\n"}
    assert picked(tree) == {CONSUMER, OTHER}
    # A dependency change in the helper itself remains a full-suite trigger.
    assert _select([st.Change("tests/pgtier.py")], tree).everything


def test_module_imports_and_collection_hooks_are_not_suppressed():
    # Import-time side effects/errors are observable even if no fixture body uses them.
    tree = {**BASE, "tests/conftest.py": "import temper_ai.alpha.source\n"}
    assert picked(tree) == {CONSUMER, OTHER}
    tree["tests/conftest.py"] = """
def pytest_configure(config):
    from temper_ai.alpha.source import value
    value()
"""
    assert picked(tree) == {CONSUMER, OTHER}


def test_nested_scope_and_same_named_sibling_fixture():
    tree = {**BASE,
            "tests/test_consumers/conftest.py": "import pytest\n" + OPTIONAL,
            "tests/test_other/conftest.py": "import pytest\n@pytest.fixture\ndef resource():\n    return 0\n",
            OTHER: "def test_plain(resource):\n    assert resource == 0\n"}
    assert picked(tree) == {CONSUMER}
    tree["tests/test_consumers/conftest.py"] += "\n@pytest.fixture(autouse=True)\ndef setup(resource):\n    pass\n"
    tree[CONSUMER] = "def test_uses():\n    assert True\n"
    assert picked(tree) == {CONSUMER}


@pytest.mark.parametrize("test_source", [
    "import pytest\n@pytest.mark.usefixtures('resource')\ndef test_uses():\n    pass\n",
    "def test_uses(request):\n    assert request.getfixturevalue('resource') == 7\n",
    "import pytest\npytestmark = pytest.mark.usefixtures('resource')\ndef test_uses():\n    pass\n",
    "import pytest\n@pytest.mark.usefixtures('resource')\nclass TestUses:\n    def test_uses(self):\n        pass\n",
])
def test_explicit_fixture_requests_and_named_fixture(test_source):
    tree = {**BASE, CONSUMER: test_source,
            "tests/conftest.py": "import pytest\n" + OPTIONAL.replace("@pytest.fixture", "@pytest.fixture(name='resource')").replace("def resource", "def original")}
    assert picked(tree) == {CONSUMER}


def test_fixture_globals_helpers_import_aliases_and_local_fixture():
    tree = {**BASE,
            "tests/conftest.py": """
import pytest
def helper():
    from temper_ai.alpha.source import value as answer
    return answer()
@pytest.fixture
def resource():
    return helper()
"""}
    assert picked(tree) == {CONSUMER}
    tree["tests/providers.py"] = "import pytest\n" + OPTIONAL.replace("def resource", "def original")
    tree["tests/conftest.py"] = "from tests.providers import original as resource\n"
    # Imported fixture bodies are traversed through the consumer, not suppressed at pgtier/conftest.
    assert CONSUMER in picked(tree)
    tree["tests/conftest.py"] = ""
    tree[CONSUMER] = "import pytest\n" + OPTIONAL + BASE[CONSUMER]
    assert picked(tree) == {CONSUMER}


def test_repository_pytest_plugin_fixture():
    tree = {**BASE, "tests/conftest.py": "pytest_plugins = ['tests.providers']\n",
            "tests/providers.py": "import pytest\n" + OPTIONAL}
    assert picked(tree) == {CONSUMER}


def test_plugin_collection_side_effects_and_changed_plugin_reach_all_consumers():
    tree = {**BASE, "tests/conftest.py": "pytest_plugins = ['tests.providers']\n",
            "tests/providers.py": "import temper_ai.alpha.source\nimport pytest\n" + OPTIONAL}
    assert picked(tree) == {CONSUMER, OTHER}
    tree["tests/providers.py"] = "import pytest\n" + OPTIONAL
    assert picked(tree, "tests/providers.py") == {CONSUMER, OTHER}


def test_repo_plugin_outside_tests_retains_its_complete_import_dependencies():
    tree = {**BASE, "tests/conftest.py": "pytest_plugins = ['support.plugin']\n",
            "support/plugin.py": "import pytest\n" + OPTIONAL}
    # No fixture slicing outside tests/: conservatively keep all plugin imports.
    assert picked(tree) == {CONSUMER, OTHER}
    # A parsed plugin loading the unsliced plugin must keep the same dependency.
    tree["tests/conftest.py"] = "pytest_plugins = ['tests.providers']\n"
    tree["tests/providers.py"] = "pytest_plugins = ['support.plugin']\n"
    assert picked(tree) == {CONSUMER, OTHER}


def test_same_named_class_fixtures_union_their_dependencies():
    tree = {**BASE, CONSUMER: """
import pytest
class TestFirst:
    @pytest.fixture
    def resource(self):
        return 0
    def test_first(self, resource):
        pass
class TestSecond:
    @pytest.fixture
    def resource(self):
        from temper_ai.alpha.source import value
        return value()
    def test_second(self, resource):
        pass
"""}
    assert picked(tree) == {CONSUMER}


@pytest.mark.parametrize("source", [
    "import pytest\n@pytest.fixture(autouse=setting)\ndef resource():\n    pass\n",
    "def test_dynamic(request, name):\n    request.getfixturevalue(name)\n",
    "pytest_plugins = choose_plugins()\n",
    "def unfinished(\n",
])
def test_unsupported_fixture_resolution_is_full_not_a_missing_edge(source):
    tree = {**BASE, CONSUMER: source}
    assert _select([st.Change(MODULE)], tree).everything
