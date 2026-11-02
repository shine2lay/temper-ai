"""Resolve known counts through xdist itself, without starting a suite or a pool."""

import sys
from types import SimpleNamespace

import pytest
from xdist import plugin as xdist

from tests import conftest, worker_defaults


@pytest.mark.parametrize(("args", "env", "expected", "warning"), [
    (["-n", "auto"], {}, 10, None),
    (["-n", "logical"], {}, 10, None),
    (["-n", "auto"], {"WT_CHECK_WORKERS": "6"}, 6, None),
    (["-n", "auto"], {"WT_CHECK_WORKERS": "6", "PYTEST_XDIST_AUTO_NUM_WORKERS": "2"}, 2, None),
    (["-n", "2"], {"WT_CHECK_WORKERS": "6", "PYTEST_XDIST_AUTO_NUM_WORKERS": "8"}, 2, None),
    ([], {"WT_CHECK_WORKERS": "6"}, None, None),
    (["-n", "0"], {"PYTEST_XDIST_AUTO_NUM_WORKERS": "6"}, 0, None),
    (["-n", "auto"], {"PYTEST_XDIST_AUTO_NUM_WORKERS": "0"}, 0, None),
    (["-n", "auto"], {"WT_CHECK_WORKERS": "0"}, 0, None),
    (["-n", "auto", "--pdb"], {"PYTEST_XDIST_AUTO_NUM_WORKERS": "6"}, 0, None),
    (["-n", "auto"], {"WT_CHECK_WORKERS": "", "PYTEST_XDIST_AUTO_NUM_WORKERS": ""}, 10, None),
    (["-n", "auto"], {"WT_CHECK_WORKERS": "bad"}, 10, "WT_CHECK_WORKERS"),
    (["-n", "auto"], {"WT_CHECK_WORKERS": "6", "PYTEST_XDIST_AUTO_NUM_WORKERS": "bad"}, 17, "PYTEST_XDIST"),
    (["-n", "2"], {"PYTEST_XDIST_AUTO_NUM_WORKERS": "bad"}, 2, None),
    (["-n", "auto"], {"CI": "true", "WT_CHECK_WORKERS": "6"}, 17, None),
    (["-n", "auto"], {"CI": ""}, 17, None),
    (["-n", "logical"], {"GITHUB_ACTIONS": "true", "WT_CHECK_WORKERS": "6"}, 17, None),
    (["-n", "auto"], {"GITHUB_ACTIONS": ""}, 17, None),
    (["-n", "auto"], {"CI": "true", "PYTEST_XDIST_AUTO_NUM_WORKERS": "2"}, 2, None),
    (["-n", "auto"], {"GITHUB_ACTIONS": "true", "PYTEST_XDIST_AUTO_NUM_WORKERS": "bad"}, 17, "PYTEST_XDIST"),
])
def test_resolved_xdist_count(tmp_path, monkeypatch, args, env, expected, warning):
    # The real parser and registered first-result hooks, but no pytest session:
    # the test must not enter wt or load a second suite's fixtures.
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    config = pytest.Config.fromdictargs({}, ["--noconftest", "--rootdir", str(tmp_path), *args, str(tmp_path)])
    config.pluginmanager.register(conftest, "temper-count-policy")
    monkeypatch.setattr(worker_defaults, "os", SimpleNamespace(environ=env))
    monkeypatch.setattr(xdist, "os", SimpleNamespace(environ=env))
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(cpu_count=lambda **kw: 17))
    try:
        if warning:
            with pytest.warns(UserWarning, match=warning):
                xdist.pytest_cmdline_main(config)
        else:
            xdist.pytest_cmdline_main(config)
        assert config.option.numprocesses == expected
        assert len(config.option.tx) == (expected or 0)
        if not expected:
            assert config.option.dist == "no"
    finally:
        config._ensure_unconfigure()


def test_native_maxprocesses_still_caps_auto(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    config = pytest.Config.fromdictargs({}, ["--noconftest", "--rootdir", str(tmp_path),
                                            "-n", "auto", "--maxprocesses", "2", str(tmp_path)])
    config.pluginmanager.register(conftest, "temper-count-policy")
    monkeypatch.setattr(worker_defaults, "os", SimpleNamespace(environ={}))
    try:
        xdist.pytest_cmdline_main(config)
        assert config.option.numprocesses == 10
        assert len(config.option.tx) == 2
    finally:
        config._ensure_unconfigure()


def test_xdist_worker_never_reenters_or_overrides(monkeypatch):
    config = SimpleNamespace(workerinput={})
    monkeypatch.setattr(worker_defaults, "os", SimpleNamespace(environ={}))
    assert conftest.pytest_xdist_auto_num_workers(config) is None

    def unexpected(*args):
        pytest.fail("an xdist worker entered placement/admission")

    monkeypatch.setattr(conftest, "enter_machine_slot", unexpected)
    conftest.pytest_configure(config)
    monkeypatch.setattr(worker_defaults, "os", SimpleNamespace(environ={"PYTEST_XDIST_WORKER": "gw0"}))
    assert conftest.pytest_xdist_auto_num_workers(SimpleNamespace()) is None
