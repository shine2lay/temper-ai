"""The switch: with TEMPER_PI_AGENT off (the default) the Pi step does not exist.

Each check runs in a fresh Python process, so nothing a test registered leaks in: the ``pi``
agent type is absent, no Pi module is imported, no ``pi_`` table is created and the server's
routes are exactly the same as with the switch on (the step adds no route at all).
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
try:
    agent.create_agent({"name": "talk", "type": "pi", "role": "scout"})
    created = "created"
except ValueError as exc:
    created = str(exc)
except Exception as exc:
    created = type(exc).__name__
print(json.dumps({
    "types": sorted(agent.AGENT_TYPES),
    "pi_modules": sorted(m for m in sys.modules if m.startswith("temper_ai.pi_agent.")
                         or m == "temper_ai.llm.pi_stream"),
    "pi_tables": [t for t in tables if t.startswith("pi_")],
    "tables": len(tables),
    "routes": routes,
    "create": created,
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


def test_switched_on_registers_only_the_type(probes):
    on, off = probes["on"], probes["unset"]
    assert "pi" in on["types"]
    assert sorted(set(on["types"]) - set(off["types"])) == ["pi"]
    assert on["create"] == "created"
    # The ledger is created by the first Pi step that runs, never at start-up.
    assert on["pi_tables"] == []
    assert on["tables"] == off["tables"]


def test_the_switch_adds_no_route(probes):
    assert probes["on"]["routes"] == probes["unset"]["routes"] == probes["off"]["routes"]


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
