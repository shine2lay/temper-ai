"""Acceptance assertions for the external calibration harness (no model/server needed)."""
from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from calibration_core import (  # noqa: E402
    Journal,
    cosine,
    digest,
    noise,
    paired_delta,
    recall,
    save,
    validate_endpoint,
    validate_path,
    wilson,
)


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_metric_formulas():
    assert recall(['a', 'b'], ['a', 'a', 'x']) == 0.5
    assert recall(['a'], ['x'] * 5 + ['a']) == 0
    assert noise([[], ['x'], []]) == 1/3
    assert paired_delta(0.8, 0.2) == pytest.approx(-0.6)
    assert cosine([1, 0], [0, 1]) == 0
    assert cosine([1, 1], [1, 1]) == pytest.approx(1)
    assert wilson(0, 16)[1] == pytest.approx(0.1936076805)
    assert wilson(1, 1)[0] > 0
    assert wilson(0, 0) is None
    with pytest.raises(ValueError):
        recall([], [])


@pytest.mark.parametrize('host,port', [('127.0.0.1', 1933), ('localhost', 1933), ('::1', 1933), ('example.com', 40001), ('127.0.0.1', 80)])
def test_zero_live_network_guard(host, port):
    with pytest.raises(PermissionError, match='E_ISOLATION_NETWORK'):
        validate_endpoint(host, port, 40001)


def test_audit_guard_blocks_actual_socket_and_open(tmp_path):
    code = "from calibration_core import install_guard; from pathlib import Path; import socket; install_guard(40001, Path(__import__('sys').argv[1])); "
    for action, marker in [("socket.create_connection(('127.0.0.1',1933))", 'E_ISOLATION_NETWORK'), ("open('/home/shinelay/.openviking/data/forbidden')", 'E_ISOLATION_PATH')]:
        result = subprocess.run([sys.executable, '-c', code + action, str(tmp_path / 'audit.jsonl')], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode != 0
        assert marker in result.stderr


@pytest.mark.parametrize('path', ['/home/shinelay/.openviking/data', '/home/shinelay/.openviking/data/a', '/home/shinelay/.pi/openviking/state', '/home/shinelay/.openviking/x/../data/a'])
def test_live_paths_forbidden(path):
    with pytest.raises(PermissionError, match='E_ISOLATION_PATH'):
        validate_path(path)


def test_resume_immutable_plan_and_no_duplicate_effects(tmp_path):
    units = [{'id': str(i), 'hash': digest(i)} for i in range(400)]
    plan = {'input_hash': 'fixed', 'units': units}
    seen = []

    def execute(unit):
        seen.append(unit['id'])
        return {'value': unit['id']}

    j = Journal(tmp_path, plan)
    assert j.run(execute, 37) == 'partial'
    prefix = j.results_path.read_bytes()
    assert Journal(tmp_path, plan).run(execute) == 'complete'
    assert j.results_path.read_bytes().startswith(prefix)
    completed = j.results_path.read_bytes()
    assert Journal(tmp_path, plan).run(execute) == 'complete'
    assert j.results_path.read_bytes() == completed
    assert seen == [str(i) for i in range(400)]
    attempts = [json.loads(x) for x in j.attempts_path.read_text().splitlines()]
    assert [a['status'] for a in attempts] == ['partial', 'complete', 'complete']
    with pytest.raises(ValueError, match='E_PLAN_HASH_CONFLICT'):
        Journal(tmp_path, {'input_hash': 'changed', 'units': units})
    assert j.results_path.read_bytes() == completed


def test_recover_stale_cursor_and_refuse_changed_result(tmp_path):
    plan = {'units': [{'id': 'a', 'hash': digest('a')}]}
    j = Journal(tmp_path, plan)
    j.run(lambda _: 4)
    save(tmp_path / 'cursor.json', {'cursor': 0, 'total': 1})
    assert Journal(tmp_path, plan).cursor == 1
    row = json.loads(j.results_path.read_text())
    row['result'] = 5
    j.results_path.write_text(json.dumps(row) + '\n')
    with pytest.raises(ValueError, match='E_UNIT_HASH_CONFLICT'):
        Journal(tmp_path, plan)


def test_gate_canonical_parity_and_frozen_cases():
    cases = json.loads((ROOT / 'cases.json').read_text())
    pairs = cases['pairs'] + [
        {'a': '`/entries` returns rows.', 'b': '`/entries` retired yesterday.'},
        {'a': 'entries returns rows.', 'b': 'entries retired yesterday.'},
        {'a': '# Déploiement\n/état actif 1.5', 'b': '/état arrêté 1.5'},
        {'a': '**Never** restart; use `pi-web-deploy`.', 'b': 'pi-web-deploy restarts.'},
    ]
    outputs = []
    for module in [ROOT / 'sources/candidate-gate.ts', Path('/home/shinelay/projects/pi-openviking/src/v2/candidate-gate.ts')]:
        if not module.exists():
            continue
        result = subprocess.run(['node', str(ROOT / 'gate_bridge.ts'), str(module)], input=json.dumps(pairs), text=True, capture_output=True, check=True)
        outputs.append(json.loads(result.stdout))
    assert all(x == outputs[0] for x in outputs)
    by_id = dict(zip([p['id'] for p in cases['pairs']], outputs[0], strict=False))
    expected = json.loads((ROOT / 'sources/acceptance.json').read_text())['cases']
    expected = next(c for c in expected if c['id'] == 'F-MEM-09')['expect']['b']
    assert all(by_id[key]['pass'] for key in expected['pass'])
    assert all(not by_id[key]['pass'] for key in expected['dropped_unrelated_by_script'])
    assert all(by_id[f'GATE-CONTROL-{i}']['pass'] for i in range(1, 5))
    assert outputs[0][-4] == {'pass': True, 'sharedIdentifiers': 1, 'sharedStems': 0}
    assert outputs[0][-3] == {'pass': False, 'sharedIdentifiers': 0, 'sharedStems': 1}
    assert len(cases['lead']) == 30 and len(cases['worker']) == 12
    assert len([p for p in cases['pairs'] if p['slice'] == 'judgment_set']) == 12
    assert len([p for p in cases['pairs'] if p['slice'] == 'frontmatter_twin']) == 6
    assert len([i for i in cases['items'] if i['state'] == 'retired']) >= 25
    assert all(p['decision'] == 'both_stay' for p in cases['pairs'] if p.get('source_case') in ('D03', 'D06', 'D07'))


def test_selection_scope_and_keyword_rules():
    selection = load('selection')
    case = {'role': 'data', 'message': 'yes', 'topic': '', 'expected': []}
    assert selection.query_of(case, 'lead', True) is None
    case['topic'] = 'Fold receipt verification'
    assert 'Fold receipt' in selection.query_of(case, 'lead', True)
    assert selection.query_of(case, 'lead', False) is None
    assert not selection.visible('viking://user/backend/memories/gotcha/x/a.md', 'data')
    assert not selection.visible('viking://user/default/memories/_legacy_v1/events/a.md', 'data')
    assert not selection.visible('viking://user/default/memories/_ejected/system/a.md', 'data')
    assert selection.visible('viking://user/default/memories/system/x/a.md', 'data')
    assert math.isfinite(cosine([0.1, 0.5], [0.2, 0.3]))
