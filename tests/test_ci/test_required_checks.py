"""The required checks have to be checks that really exist.

A branch protected on a check nobody ever posts is a branch that can never
move again — and the only way out is the emergency switch, by hand, from a
phone. So the list in `temper-ci protect` is checked here against the workflow
that actually posts them, and against what `wt land` waits for.

If you rename a job in ci.yml, this test fails, and that is the whole point.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

CI_YML = REPO / ".github" / "workflows" / "ci.yml"
WT_YAML = Path.home() / "projects" / "agent-tools" / "wt.yaml"


def check_names_in(workflow: str) -> set[str]:
    """What GitHub will call each job of this workflow.

    A job's check is its `name:` if it has one, else its key; a matrix
    expands `${{ matrix.x }}` once per value. Read plainly rather than with a
    YAML library, because what is wanted is the *displayed* name, which is a
    template, not a value.
    """
    text = workflow
    names: set[str] = set()
    for m in re.finditer(r"^  ([a-z][\w-]*):\n((?:    .*\n|\n)*)", text, re.M):
        key, body = m.group(1), m.group(2)
        if key in {"push", "pull_request", "schedule", "workflow_dispatch"}:
            continue
        got = re.search(r"^    name: (.+)$", body, re.M)
        name = got.group(1).strip().strip("'\"") if got else key
        matrix = re.search(r"^        ([\w-]+): \[(.+)\]$", body, re.M)
        if matrix and f"matrix.{matrix.group(1)}" in name:
            for value in [v.strip().strip("'\"") for v in matrix.group(2).split(",")]:
                names.add(re.sub(r"\$\{\{\s*matrix\.[\w-]+\s*\}\}", value, name))
        else:
            names.add(name)
    return names


@pytest.fixture
def required() -> list[str]:
    from temper_ci.cli import PROTECTION  # noqa: PLC0415

    return list(PROTECTION["required_status_checks"]["contexts"])


def test_every_required_check_is_one_ci_really_posts(required):
    """The deadlock this prevents: master waiting forever on a job that was
    renamed, or never existed."""
    posted = check_names_in(CI_YML.read_text(encoding="utf-8"))
    posted.add("temper/boxes")          # this machine posts that one, not GitHub
    missing = [c for c in required if c not in posted]
    assert not missing, (
        f"master would wait forever for {missing}. ci.yml posts: {sorted(posted)}")


def test_the_machine_check_is_required(required):
    """Without it, master is protected only by GitHub's own runners, and the
    whole point of this task is the check that runs a real temper."""
    assert "temper/boxes" in required


def test_ci_runs_on_every_branch_so_a_land_has_something_to_wait_for():
    """`wt land` pushes a branch and waits. If ci.yml only ran on master or on
    pull requests, it would wait for checks that never start."""
    text = CI_YML.read_text(encoding="utf-8")
    on = re.search(r"^on:(.*?)^\w", text, re.S | re.M)
    assert on, "ci.yml has no 'on:' block"
    assert re.search(r"push:\s*\n\s*branches: \['\*\*'\]", on.group(1)), \
        "ci.yml must run on a push to every branch, or wt land waits for nothing"


def test_a_newer_push_cancels_the_older_one():
    """Two pushes a minute apart should not both hold a runner: the older
    answer is about code nobody is landing any more."""
    text = CI_YML.read_text(encoding="utf-8")
    assert "cancel-in-progress: true" in text
    group = re.search(r"group: (.+)", text)
    assert group and "github.ref" in group.group(1), \
        "the concurrency group has to be per branch, or one branch cancels another's checks"


@pytest.mark.skipif(not WT_YAML.exists(), reason="agent-tools is not checked out here")
def test_wt_waits_for_the_same_checks_protection_requires(required):
    """Two lists that must agree \u2014 once both exist.

    If `wt land` waited for fewer checks than protection requires, it would
    land something GitHub then refuses; if it waited for one nobody posts, it
    would hang. But the two live in different repositories, and one of them has
    to land first, so a missing list means "the gate is not in use here yet",
    not "the gate is wrong". Only a list that exists and disagrees is a bug.
    """
    text = WT_YAML.read_text(encoding="utf-8")
    block = re.search(r"^  temper-ai:\n((?:    .*\n|\n)*)", text, re.M)
    if not block:
        pytest.skip("this machine's wt.yaml has no temper-ai entry")
    waits = [w.strip().strip("'\"") for w in re.findall(r"^      - (.+)$", block.group(1), re.M)]
    if not waits:
        pytest.skip("wt.yaml does not land temper-ai through the gate yet "
                    "(no required_checks); nothing to disagree with")
    assert set(waits) == set(required), (
        f"wt land waits for {sorted(set(waits) - set(required))} that protection does not "
        f"require, and misses {sorted(set(required) - set(waits))} that it does")
