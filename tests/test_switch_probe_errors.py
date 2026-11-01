"""Switch probe exit assertions never reproduce the child's streams or argv."""

import subprocess
import uuid
from types import SimpleNamespace

import pytest

from tests.test_pi_agent import test_lane_view, test_switch


@pytest.mark.parametrize("module", [test_switch, test_lane_view])
def test_failed_probe_assertion_withholds_child_output(module, tmp_path, monkeypatch):
    tokens = [uuid.uuid4().hex for _ in range(3)]
    child = subprocess.CompletedProcess([tokens[0]], 7, tokens[1], tokens[2])
    monkeypatch.setattr(module, "subprocess", SimpleNamespace(run=lambda *a, **k: child))
    with pytest.raises(AssertionError) as caught:
        if module is test_switch:
            module._probe(tmp_path, None)
        else:
            module.test_switched_off_nothing_imports_the_view_and_there_is_no_team_api(tmp_path)
    # Render the probe's failing frame, not this harness's source (which names
    # CompletedProcess literally). Preserve verbose rewritten-assert output.
    text = str(caught.value) + str(caught.getrepr(
        funcargs=True, style="long", chain=True, tbfilter=lambda exc: exc.traceback[-1:]))
    leaked = any(token in text for token in tokens)
    assert not leaked
    assert "CompletedProcess(" not in text
    assert "probe failed" in text
