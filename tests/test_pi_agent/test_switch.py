"""The switch: with TEMPER_PI_AGENT off (the default) the Pi step and the team strategy do not
exist.

Each check runs in a fresh Python process, so nothing a test registered leaks in: the ``pi``
agent type and the ``team`` strategy are absent, no strategy has a run-start check (so a run's
workflow loads exactly as before), no Pi module is imported, no ``pi_`` table is created and the
server's routes are exactly the same as with the switch on (the step adds no route at all).

The team messaging pieces (#37) are covered the same way: their modules are not imported, a
cancelled run's cancel path imports nothing and creates no table, and a team stage with Pi
members is refused as an unknown strategy (R2 B14).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from tests.test_pi_agent.support import WORKTREE

PROBE = r"""
import json, sys
import temper_ai.agent as agent
from temper_ai.database import init_database
url = sys.argv[1]
init_database(url)
import sqlalchemy as sa
from temper_ai.database import get_database
tables = sorted(sa.inspect(get_database().engine).get_table_names())
from temper_ai.server import app
routes = sorted(f"{sorted(getattr(r, 'methods', None) or [])} {r.path}" for r in app.routes)
from temper_ai.stage import topology
try:
    agent.create_agent({"name": "talk", "type": "pi", "role": "scout"})
    created = "created"
except ValueError as exc:
    created = str(exc)
except Exception as exc:
    created = type(exc).__name__
# A team stage with Pi members (R2 B14).
try:
    topology.build_topology("team", [{"name": "lead", "type": "pi", "role": "scout"},
                                     {"name": "builder", "type": "pi", "role": "scout"}],
                            {"mode": {"type": "leader", "leader": "lead"},
                             "communication": {"type": "all"}, "pause_after_rounds": 3})
    team_stage = "built"
except Exception as exc:
    team_stage = f"{type(exc).__name__}: {exc}"
# The cancel path of a parked run (R2 C2) and the sweep that ends a cancelled run's teams
# later (G-a, #38): with the switch off they import and create nothing.
from temper_ai.runner import parked
parked._end_pi_teams("run-probe")
swept = parked.end_cancelled_pi_teams()
tables_after = sorted(sa.inspect(get_database().engine).get_table_names())
print(json.dumps({
    "types": sorted(agent.AGENT_TYPES),
    "pi_modules": sorted(m for m in sys.modules if m.startswith("temper_ai.pi_agent.")
                         or m == "temper_ai.llm.pi_stream"),
    "pi_tables": [t for t in tables_after if t.startswith("pi_")],
    "team_stage": team_stage,
    "tables": len(tables),
    "routes": routes,
    "create": created,
    "strategies": topology.available_strategies(),
    "run_start": topology.run_start_options(),
    "team_check": topology.run_start_check("team") is not None,
    "swept": swept,
}))
"""


def _probe(tmp_path, switch: str | None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TEMPER_PI_")}
    env.pop("TEMPER_DATABASE_URL", None)
    if switch is not None:
        env["TEMPER_PI_AGENT"] = switch
    env.update({"PYTHONPATH": str(WORKTREE), "TEMPER_EXECUTION_MODE": "inprocess",
                "TEMPER_LOG_DIR": str(tmp_path / f"logs-{switch}")})
    url = f"sqlite:///{tmp_path / f'switch-{switch}.db'}"
    out = subprocess.run([sys.executable, "-c", PROBE, url], cwd=WORKTREE, env=env,
                         capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr[-3000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def probes(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("pi-switch")
    return {"unset": _probe(tmp, None), "off": _probe(tmp, "0"), "on": _probe(tmp, "1")}


@pytest.mark.parametrize("which", ["unset", "off"])
def test_switched_off_the_pi_type_and_its_code_are_absent(probes, which):
    got = probes[which]
    assert "pi" not in got["types"]
    assert got["pi_modules"] == []
    assert got["pi_tables"] == []
    assert got["create"].startswith("Unknown agent type: 'pi'")
    assert got["strategies"] == ["parallel", "sequential", "leader"]
    assert got["run_start"] == {}
    assert got["team_check"] is False
    # R2 B14: a team stage with Pi members is refused with a clear message, and the cancel
    # path (C2) and the G-a sweep neither imported the team code nor created a table (both
    # checked above).
    assert got["team_stage"].startswith("TopologyError: Unknown strategy: 'team'")
    assert got["swept"] == 0


def test_b14_switch_off_creates_nothing(probes):
    """R2 B14 in one place: with TEMPER_PI_AGENT unset no ``pi_`` table is created (not even by
    a cancel), no Pi or team module is imported, and a team stage with Pi members is refused
    with a clear message -- #20's refusal (the strategy does not exist), not a second one."""
    got = probes["unset"]
    assert got["pi_tables"] == []
    assert got["pi_modules"] == []
    assert got["team_stage"].startswith("TopologyError: Unknown strategy: 'team'")
    assert not [r for r in got["routes"] if "/api/team" in r]


def test_switched_off_no_team_messaging_module_is_imported(probes):
    """R2 B14 for #37: the router, inbox framing and team runtime stay out of a switched-off
    Temper; switched on, the team runtime loads only when a team runs, never at start-up."""
    team_modules = {"temper_ai.pi_agent.route", "temper_ai.pi_agent.route.router",
                    "temper_ai.pi_agent.route.policy", "temper_ai.pi_agent.route.model",
                    "temper_ai.pi_agent.inbox", "temper_ai.pi_agent.team_runtime",
                    "temper_ai.pi_agent.ledger"}
    for which in ("unset", "off"):
        loaded = set(probes[which]["pi_modules"])
        assert not loaded & team_modules, (which, sorted(loaded & team_modules))
    assert "temper_ai.pi_agent.team_runtime" not in probes["on"]["pi_modules"]


def test_switched_on_registers_only_the_type_and_the_team_strategy(probes):
    on, off = probes["on"], probes["unset"]
    assert "pi" in on["types"]
    assert sorted(set(on["types"]) - set(off["types"])) == ["pi"]
    assert on["create"] == "created"
    assert on["strategies"] == ["parallel", "sequential", "leader", "team"]
    assert on["run_start"] == {"run_start": True}
    assert on["team_check"] is True
    # The ledger is created by the first Pi step that runs, never at start-up, and neither the
    # cancel path nor the G-a sweep creates it (R2 C2).
    assert on["pi_tables"] == []
    assert on["swept"] == 0
    assert on["tables"] == off["tables"]
    # Switched on, the team stage builds; its team node runs the leader loop (#38).
    assert on["team_stage"] == "built"


#: The Team page's API (M3): the only routes the switch adds, all under /api/team.
TEAM_ROUTES = [
    "['POST'] /api/team/check",
    "['GET'] /api/team/roles",
    "['GET'] /api/team/runs/{execution_id}",
    "['GET'] /api/team/runs/{execution_id}/messages/{message_id}",
    "['GET'] /api/team/status",
    "['GET'] /api/team/trials",
    "['POST'] /api/team/runs/{execution_id}/messages",
    "['POST'] /api/team/runs/{execution_id}/waits/{wait_id}/answer",
    "['POST'] /api/team/trials",
]


def test_the_switch_adds_only_the_team_page_routes(probes):
    """Switched off (unset or off) Temper has exactly the routes it had before #48; switched
    on it adds the Team page's nine, all under /api/team, and changes no other route."""
    assert probes["unset"]["routes"] == probes["off"]["routes"]
    added = sorted(set(probes["on"]["routes"]) - set(probes["off"]["routes"]))
    assert added == sorted(TEAM_ROUTES)
    assert set(probes["off"]["routes"]) <= set(probes["on"]["routes"])


def test_only_exact_on_words_switch_it_on(monkeypatch):
    from temper_ai import pi_agent

    for value in ("1", "true", "ON", " yes "):
        monkeypatch.setenv(pi_agent.SWITCH_ENV, value)
        assert pi_agent.enabled()
    for value in ("", "0", "false", "off", "no", "enabled", "2"):
        monkeypatch.setenv(pi_agent.SWITCH_ENV, value)
        assert not pi_agent.enabled()
    monkeypatch.delenv(pi_agent.SWITCH_ENV)
    assert not pi_agent.enabled()
    assert pi_agent.register_if_enabled() is False
    assert pi_agent.register_team_if_enabled() is False
