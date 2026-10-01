"""The repo copies a question may be answered from.

`repo_answer` step 1 (`configs/agents/repo_copies.yaml`) makes a read-only
copy of each repository. A role that may only ask about some of them puts
that list in `only`, and then no other repository is copied, named, or left
anywhere the answerer's Read, Grep and Glob could reach it — that is the
whole fence around `/temper ask`, so it is tested against the real config.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml
from jinja2 import BaseLoader, ChainableUndefined
from jinja2.sandbox import SandboxedEnvironment

from temper_ai.agent.script_agent import (
    BARE_FILTER,
    ENV_FILTER,
    QUOTED_FILTER,
    _rewrite_interpolations,
    _ValueStash,
)

CONFIG = Path(__file__).resolve().parents[2] / "configs" / "agents" / "repo_copies.yaml"


def rendered(**inputs: str | None) -> tuple[str, dict[str, str]]:
    """The script and the environment, exactly as ScriptAgent prepares them."""
    config = yaml.safe_load(CONFIG.read_text())["agent"]
    stash = _ValueStash()
    env = SandboxedEnvironment(loader=BaseLoader(), undefined=ChainableUndefined)
    env.filters[QUOTED_FILTER] = stash.quoted
    env.filters[BARE_FILTER] = stash.bare
    env.filters[ENV_FILTER] = stash.name
    script = env.from_string(_rewrite_interpolations(config["script_template"], config["name"])).render(**inputs)
    return script, dict(stash.env)


def run(script: str, environment: dict[str, str], home: Path) -> dict:
    """Run it against folders of our own, with no deploy keys and nowhere to
    clone from: every repository comes back missing, which is enough to see
    *which* ones it went looking for."""
    done = subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=120,
                          env={"PATH": "/usr/bin:/bin", "HOME": str(home),
                               "REPO_COPIES_ROOT": str(home / "readonly"),
                               "REPO_COPIES_KEYS": str(home / "keys"), **environment})
    last = [line for line in done.stdout.splitlines() if line.startswith("{")]
    return json.loads(last[-1]) if last else {"stdout": done.stdout, "stderr": done.stderr}


def test_the_script_parses_under_sh():
    script, _env = rendered(only="roamee")
    assert subprocess.run(["sh", "-n", "-c", script], capture_output=True, timeout=30).returncode == 0


def test_the_value_travels_in_the_environment_not_in_the_text():
    """A quoted heredoc expands nothing, so a value written into the script
    would arrive as the text `$TEMPER_V1` and quietly match no repository."""
    script, environment = rendered(only="roamee")
    assert "roamee" in environment.values(), environment
    body = script.split("<<'PY'", 1)[1]
    assert "{{" not in body and "$TEMPER_V" not in body


ALL = ["rollcall", "roamee", "temper-ai"]


@pytest.mark.parametrize("only,expected", [
    ("roamee", ["roamee"]),
    ("roamee,temper-ai", ["roamee", "temper-ai"]),
    ("", ALL),
    # Nobody filled the input in: the engine hands the step None, not "".
    (None, ALL),
])
def test_only_the_named_repositories_are_touched(only, expected, tmp_path):
    script, environment = rendered(only=only)
    got = run(script, environment, tmp_path)
    assert [e["name"] for e in got.get("repos", [])] == expected, got


@pytest.mark.parametrize("inputs", [{}, {"only": None}])
def test_an_unfilled_input_asks_for_every_repository(inputs, tmp_path):
    """A workflow input with no value reaches a script step as None, and
    `str(None)` is the word "None": without `default('', true)` every ask
    went looking for a repository called None and failed (2026-10-01, live).
    """
    script, environment = rendered(**inputs)
    assert "None" not in environment.values(), environment
    got = run(script, environment, tmp_path)
    assert [e["name"] for e in got.get("repos", [])] == ALL, got


def test_a_repository_nobody_may_ask_about_is_not_even_named(tmp_path):
    script, environment = rendered(only="roamee")
    got = run(script, environment, tmp_path)
    assert "rollcall" not in json.dumps(got)


def test_a_name_that_is_no_repository_fails_rather_than_answering_from_all(tmp_path):
    script, environment = rendered(only="not-a-repo")
    got = run(script, environment, tmp_path)
    assert got.get("status") == "failed" and "no such repository" in got.get("error", "")


def fake_copy(home: Path, name: str) -> None:
    """A copy that is already there and fresh, so the script keeps it instead
    of fetching (there is no network here, and no deploy key)."""
    where = home / "readonly" / name
    where.mkdir(parents=True, exist_ok=True)
    for args in (("init", "-q", "-b", "main"), ("-c", "user.email=t@t", "-c", "user.name=t",
                                                 "commit", "-q", "--allow-empty", "-m", "copy")):
        subprocess.run(["git", *args], cwd=where, check=True, capture_output=True)
    (home / "readonly" / f".{name}.fetched").touch()


def test_one_repository_alone_hands_on_its_own_folder(tmp_path):
    """With a single repository the workspace is that repository's folder,
    so Read, Grep and Glob cannot reach another even by path."""
    fake_copy(tmp_path, "roamee")
    script, environment = rendered(only="roamee")
    got = run(script, environment, tmp_path)
    assert got["status"] == "ready" and got["workspace"].endswith("/readonly/roamee")
    assert got["summary"].startswith("- ./ (roamee)"), got["summary"]


def test_several_repositories_hand_on_the_folder_above_them(tmp_path):
    fake_copy(tmp_path, "roamee")
    fake_copy(tmp_path, "rollcall")
    script, environment = rendered(only="")
    got = run(script, environment, tmp_path)
    assert got["workspace"].endswith("/readonly") and "- roamee/:" in got["summary"]
