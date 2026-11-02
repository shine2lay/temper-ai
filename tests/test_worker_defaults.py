"""Resolve known counts through xdist itself, without starting a suite or a pool."""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from xdist import plugin as xdist

from tests import conftest, worker_defaults


@pytest.mark.parametrize(("args", "env", "expected", "warning"), [
    (["-n", "auto"], {}, 10, None),
    (["-n", "logical"], {}, 10, None),
    (["-n", "auto"], {"WT_CHECK_WORKERS": "2"}, 2, None),
    (["-n", "auto"], {"WT_CHECK_WORKERS": "6"}, 6, None),
    (["-n", "auto"], {"WT_CHECK_WORKERS": "10"}, 10, None),
    (["-n", "auto"], {"WT_CHECK_WORKERS": "6", "PYTEST_XDIST_AUTO_NUM_WORKERS": "2"}, 2, None),
    (["-n", "2"], {"WT_CHECK_WORKERS": "6", "PYTEST_XDIST_AUTO_NUM_WORKERS": "8"}, 2, None),
    ([], {"WT_CHECK_WORKERS": "6"}, None, None),
    (["-n", "0"], {"PYTEST_XDIST_AUTO_NUM_WORKERS": "6"}, 0, None),
    (["-n", "auto"], {"PYTEST_XDIST_AUTO_NUM_WORKERS": "0"}, 0, None),
    (["-n", "auto"], {"WT_CHECK_WORKERS": "0"}, 0, None),
    (["-n", "auto", "--pdb"], {"PYTEST_XDIST_AUTO_NUM_WORKERS": "6"}, 0, None),
    (["-n", "auto"], {"PYTEST_XDIST_AUTO_NUM_WORKERS": ""}, 10, None),
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


@pytest.mark.parametrize("shared", ["", "bad-private-value", "-1", "1.5", "2suffix", "2\n", " 2", "+2", "2e1", "0x2", "２"])
def test_consumed_shared_input_fails_during_resolution(tmp_path, monkeypatch, shared):
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    config = pytest.Config.fromdictargs({}, ["--noconftest", "--rootdir", str(tmp_path), "-n", "auto", str(tmp_path)])
    config.pluginmanager.register(conftest, "temper-count-policy")
    monkeypatch.setattr(worker_defaults, "os", SimpleNamespace(environ={"WT_CHECK_WORKERS": shared}))
    try:
        with pytest.raises(pytest.UsageError) as error:
            xdist.pytest_cmdline_main(config)
        assert str(error.value) == "WT_CHECK_WORKERS must be a nonnegative whole-number count; unset it for the local default."
        assert not config.option.tx  # No worker specifications were made.
    finally:
        config._ensure_unconfigure()


@pytest.mark.parametrize("shared", ["", "bad", "-1", "1.5", "2suffix"])
@pytest.mark.parametrize(("args", "override", "expected", "warning"), [
    (["-n", "2"], {}, 2, None),
    (["-n", "0"], {}, 0, None),
    ([], {}, None, None),
    (["-n", "auto", "--pdb"], {}, 0, None),
    (["-n", "auto"], {"PYTEST_XDIST_AUTO_NUM_WORKERS": "2"}, 2, None),
    (["-n", "auto"], {"PYTEST_XDIST_AUTO_NUM_WORKERS": "bad"}, 17, "PYTEST_XDIST"),
    (["-n", "auto"], {"CI": "true"}, 17, None),
    (["-n", "auto"], {"GITHUB_ACTIONS": ""}, 17, None),
])
def test_unused_shared_input_keeps_native_resolution(tmp_path, monkeypatch, shared, args, override, expected, warning):
    test_resolved_xdist_count(tmp_path, monkeypatch, args, {"WT_CHECK_WORKERS": shared, **override}, expected, warning)


@pytest.mark.parametrize(("shared", "expected_code", "ran"), [("", 4, False), ("bad", 4, False), ("-1", 4, False), ("1.5", 4, False), ("0", 0, True)])
def test_shared_validation_precedes_child_test_processing(tmp_path, shared, expected_code, ran):
    test = tmp_path / "test_sentinel.py"
    test.write_text("from pathlib import Path\nPath(__file__).with_suffix('.collected').touch()\n"
                    "def test_body():\n    Path(__file__).with_suffix('.ran').touch()\n")
    env = {key: value for key, value in os.environ.items() if key not in {
        "CI", "GITHUB_ACTIONS", "PYTEST_XDIST_WORKER", "PYTEST_XDIST_AUTO_NUM_WORKERS", "PYTEST_ADDOPTS",
    }}
    env.update(WT_CHECK_WORKERS=shared, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
               PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    try:
        # -c /dev/null also changes the default confcutdir. Keep collection
        # within this fixture instead of enumerating shared /tmp ancestors.
        code = subprocess.run([sys.executable, "-m", "pytest", "-c", "/dev/null", "--rootdir", str(tmp_path),
                               "--confcutdir", str(tmp_path), "--noconftest", "-p", "xdist.plugin", "-p", "tests.worker_defaults", "-n", "auto", str(test)],
                              cwd=tmp_path, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=20).returncode
    except (OSError, subprocess.SubprocessError):
        raise AssertionError("worker configuration probe did not finish") from None
    assert code == expected_code
    assert test.with_suffix(".collected").exists() is ran
    assert test.with_suffix(".ran").exists() is ran


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
    monkeypatch.setattr(worker_defaults, "os", SimpleNamespace(environ={"WT_CHECK_WORKERS": "bad"}))
    assert conftest.pytest_xdist_auto_num_workers(config) is None

    def unexpected(*args):
        pytest.fail("an xdist worker entered placement/admission")

    monkeypatch.setattr(conftest, "enter_machine_slot", unexpected)
    conftest.pytest_configure(config)
    monkeypatch.setattr(worker_defaults, "os", SimpleNamespace(environ={"PYTEST_XDIST_WORKER": "gw0", "WT_CHECK_WORKERS": "bad"}))
    assert conftest.pytest_xdist_auto_num_workers(SimpleNamespace()) is None
