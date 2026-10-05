"""The smoke set's own behaviour: what it checks, and when it gives up.

Not the checks themselves — those need a real stack, and the gate runs them
against one on every push. These are about the shape of the set.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from temper_ci import smoke  # noqa: E402


class _Box:
    """Stands in for a throwaway temper. Nothing here touches anything real."""

    project = "temper-box-test"
    api = "http://127.0.0.1:1"


def test_it_stops_at_the_first_failure(monkeypatch, tmp_path):
    """A properly broken stack fails every check, and each one waits its full
    three minutes first. Carrying on would take twenty-five minutes to repeat
    what the first one said, while every other land waits behind it.
    """
    called: list[str] = []

    def named(name):
        def fn(*_a, **_k):
            called.append(name)
            if name == "gate_through_api":
                raise smoke.BoxError("the gate never opened")
            return f"{name} ok"
        return fn

    for fn_name in ("plain_run", "box_env", "parallel_and_stage", "gate_through_api",
                    "write_guard", "stop_then_resume", "fork", "restart_mid_run", "hooks"):
        monkeypatch.setattr(smoke, fn_name, named(fn_name))
    monkeypatch.setattr(smoke, "finished_run_page", lambda box, shots: ("page ok", []))

    results = smoke.run_all(_Box(), tmp_path)

    assert [r.name for r in results] == ["plain run", "box env", "parallel and stage", "gate"]
    assert results[-1].ok is False
    assert "stop_then_resume" not in called, "it carried on after the answer was in"


def test_everything_passing_runs_the_whole_set(monkeypatch, tmp_path):
    for fn_name in ("plain_run", "box_env", "parallel_and_stage", "gate_through_api",
                    "write_guard", "stop_then_resume", "fork", "restart_mid_run", "hooks"):
        monkeypatch.setattr(smoke, fn_name, lambda *a, **k: "ok")
    monkeypatch.setattr(smoke, "finished_run_page", lambda box, shots: ("page ok", ["a.png"]))

    results = smoke.run_all(_Box(), tmp_path)

    assert all(r.ok for r in results)
    assert len(results) == smoke.SET_SIZE, (
        "SET_SIZE is what the gate uses to say how much it did not reach; "
        "it has drifted from the set itself")


@pytest.mark.parametrize("promised", ["plain run", "parallel and stage", "gate",
                                      "stop and resume", "fork", "server restart mid-run",
                                      "the page", "hooks", "box env", "write guard"])
def test_the_set_is_the_things_that_were_promised(monkeypatch, tmp_path, promised):
    """The eight in the first task, the box's environment (docs/boxes.md) and the write
    guard (docs/api-access.md). If one is dropped, the gate goes on saying it checked,
    and nobody finds out until the thing it covered breaks live.
    """
    for fn_name in ("plain_run", "box_env", "parallel_and_stage", "gate_through_api",
                    "write_guard", "stop_then_resume", "fork", "restart_mid_run", "hooks"):
        monkeypatch.setattr(smoke, fn_name, lambda *a, **k: "ok")
    monkeypatch.setattr(smoke, "finished_run_page", lambda box, shots: ("page ok", []))

    names = [r.name for r in smoke.run_all(_Box(), tmp_path)]

    assert promised in names
