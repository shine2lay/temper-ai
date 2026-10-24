"""#125 stages 4b (W1 admission refusal) and 4c (Security N1 total CLOSE reader): fixed fakes only.

No browser, MCP service, network, docker or host action: open_session is replaced by a counter that fails the
test if it is ever entered, and every receipt and W2 record is a fixed file under tmp_path.
"""
import asyncio
import contextlib
import hashlib
import importlib.util
import json
import os
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BIN = Path(__file__).resolve().parents[2] / 'configs/architecture/bin'
if 'first_app_p3' not in sys.modules:
    spec = importlib.util.spec_from_file_location('first_app_p3', BIN / 'first_app_p3.py')
    p3 = importlib.util.module_from_spec(spec)
    sys.modules['first_app_p3'] = p3
    spec.loader.exec_module(p3)
p3 = sys.modules['first_app_p3']
g = p3.guard
adm = getattr(p3, 'admission', None)  # absent on the pre-#125 base, where the first-miss run imports this file
ORIGIN = 'http://100.110.162.4:8962'
EXACT = 'https://outside.invalid/n1?' + 'fixed=abcdef&' * 40 + 'end=last'
CR = 'http://playwright-mcp:8931/mcp'
WK = 'http://playwright-mcp-webkit:8931/mcp'
OLD = 'a' * 64
NEW = 'b' * 64
FAILED_AT = '2026-10-24T08:00:00.000+00:00'
NEW_START = '2026-10-24T09:00:00.123456789Z'


@pytest.fixture(autouse=True)
def forbid_real_operations(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError('stage tests must never connect/start a real service')

    monkeypatch.setattr(p3.http.server, 'ThreadingHTTPServer', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)


@pytest.fixture
def mcp_calls(monkeypatch):
    calls = []

    @contextlib.asynccontextmanager
    async def counted(url):
        calls.append(url)
        raise AssertionError('MCP session opened: ' + url)
        yield  # pragma: no cover

    async def probe(*a, **kw):
        calls.append('probe_session')
        raise AssertionError('MCP probe opened')

    monkeypatch.setattr(p3, 'open_session', counted)
    monkeypatch.setattr(p3, 'probe_session', probe)
    return calls


def receipt(root, run, *, service=WK, finished=FAILED_AT, recreation=True, case=None, w1=OLD, **extra):
    d = {'journey': 'p3', 'finished_at': finished, 'probe_services': {},
         'sessions': {'webkit' if service == WK else 'chromium': {'url': service, 'status': 'RAN'}},
         'cleanup': {'webkit' if service == WK else 'chromium': {'confirmed': not recreation}},
         'mcp_service_recreation_required': [{'service': service, 'phase': 'cleanup', 'reason': 'fixed'}]
         if recreation else []}
    if service == WK and w1:
        d['engine_image'] = {'service': WK, 'before': {'status': 'PASS', 'facts': {'container_id': w1}}}
    d.update(extra)
    folder = root / run / 'check' / (case or '')
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'receipt.json').write_text(json.dumps(d))
    return folder / 'receipt.json'


def w2_record(tmp_path, *, cid=NEW, started=NEW_START, mode='after', running=True, name='after.json',
              svc='playwright-mcp-webkit'):
    data = json.dumps({'at': '2026-10-24T09:01:00Z', 'mode': mode, 'containers': {
        svc: {'id': cid, 'name': 'x', 'started_at': started, 'running': running}}}).encode()
    path = tmp_path / name
    path.write_bytes(data)
    return {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest()}


def w1(cid=NEW, started=NEW_START, status='PASS'):
    return {'operation': 'engine-image', 'status': status, 'reasons': [],
            'facts': {'image_id': 'sha256:' + 'c' * 64, 'container_id': cid, 'container_started_at': started,
                      'running': True}}


def root_of(tmp_path):
    root = tmp_path / 'root'
    root.mkdir(parents=True, exist_ok=True)
    return root


# ---- 4b: the six planned admission cases (plus the guards around them) ----

def test_no_earlier_recreation_admits(tmp_path):
    root = root_of(tmp_path)
    receipt(root, 'r1', recreation=False)
    (root / 'legacy' / 'check').mkdir(parents=True)
    (root / 'legacy' / 'check' / 'receipt.json').write_text(json.dumps({'mode': 'controls', 'verdict': 'PASS'}))
    got = adm.admit(root, WK, need_w1=True)
    assert got['status'] == 'ADMITTED' and got['p3_receipts'] == 1 and got['receipts_read'] == 2
    assert adm.admit(root_of(tmp_path / 'empty'), CR)['status'] == 'ADMITTED'


def test_recreation_without_w2_blocks_with_zero_mcp_calls(tmp_path, mcp_calls):
    root = root_of(tmp_path)
    receipt(root, 'r1', case='CASE1')
    got = adm.admit(root, WK, need_w1=True)
    assert got['status'] == 'BLOCKED' and got['recreation_required']
    assert 'no Ops W2 recreation receipt' in got['reasons'][0]
    # The same refusal inside the journey: the Chromium service is admitted (never used), WebKit is not.
    t = SimpleNamespace(receipts_root=root, receipts_out_name='check', w2_recreation=None)
    target = {'origin': ORIGIN, 'pins': {}}
    p3.bind_admission(target, t)
    r, latch = {'sessions': {}, 'steps': []}, g.StopLatch()
    assert p3.admitted(r, latch, target, CR, webkit=False)
    assert not p3.admitted(r, latch, target, WK, webkit=True)
    assert latch.blocked and r['admission'][WK]['status'] == 'BLOCKED'
    assert mcp_calls == []


def test_journey_refuses_before_its_first_mcp_call(tmp_path, mcp_calls):
    root = root_of(tmp_path)
    receipt(root, 'r1', service=CR)
    target = {'origin': ORIGIN, 'pins': {}, 'receipts_root': str(root), 'receipts_out_name': 'check'}
    r = asyncio.run(p3.check_target(CR, WK, target, tmp_path / 'out', 'R', tmp_path / 'out' / 'host', 900,
                                    latch=g.StopLatch(), persist=False,
                                    receipt=p3.new_receipt('R', None)))
    assert mcp_calls == [] and r['exit_code'] == 3 and r['verdict'] == 'BLOCKED'
    assert r['admission'][CR]['status'] == 'BLOCKED' and 'no MCP call' in r['runner_error']
    no_root = asyncio.run(p3.check_target(CR, WK, {'origin': ORIGIN, 'pins': {}}, tmp_path / 'o2', 'R',
                                          tmp_path / 'o2' / 'host', 900, persist=False,
                                          receipt=p3.new_receipt('R', None)))
    assert mcp_calls == [] and no_root['exit_code'] == 3
    assert 'no absolute receipts root' in no_root['admission'][CR]['reasons'][0]


@pytest.mark.parametrize('fault', ['same_id', 'earlier_start', 'equal_start', 'not_running', 'before_mode'])
def test_w2_not_a_new_later_container_blocks(tmp_path, fault):
    root = root_of(tmp_path)
    receipt(root, 'r1')
    cid = OLD if fault == 'same_id' else NEW
    started = {'earlier_start': '2026-10-24T07:59:59Z', 'equal_start': FAILED_AT}.get(fault, NEW_START)
    ref = w2_record(tmp_path, cid=cid, started=started, running=fault != 'not_running',
                    mode='before' if fault == 'before_mode' else 'after')
    # The W1 reading matches the W2 container, so only the named fault can refuse (mutation M-c found the
    # first version refusing equal_start through a W1 start mismatch instead).
    got = adm.admit(root, WK, w2={WK: ref}, w1_before=w1(cid, started), need_w1=True)
    assert got['status'] == 'BLOCKED', got
    reason = {'same_id': 'same container id', 'earlier_start': 'is not later than', 'equal_start': 'is not later than',
              'not_running': 'is not running', 'before_mode': 'not an after-recreation record'}[fault]
    assert reason in got['reasons'][0], got


def test_w2_hash_mismatch_blocks(tmp_path):
    root = root_of(tmp_path)
    receipt(root, 'r1')
    ref = w2_record(tmp_path)
    ref['sha256'] = '0' * 64
    got = adm.admit(root, WK, w2={WK: ref}, w1_before=w1(), need_w1=True)
    assert got['status'] == 'BLOCKED' and 'is not the named' in got['reasons'][0]


def test_valid_w2_and_matching_w1_admits(tmp_path):
    root = root_of(tmp_path)
    receipt(root, 'r1')
    ref = w2_record(tmp_path)
    got = adm.admit(root, WK, w2={WK: ref}, w1_before=w1(), need_w1=True)
    assert got['status'] == 'ADMITTED' and got['w2']['after']['container_id'] == NEW
    assert got['w2']['w1_before']['container_id'] == NEW
    # WebKit needs the fresh W1 reading to be that container: missing, other id, other start or not PASS -> no.
    for bad in (None, w1(cid='d' * 64), w1(started='2026-10-24T09:00:00.123457Z'), w1(status='BLOCKED')):
        assert adm.admit(root, WK, w2={WK: ref}, w1_before=bad, need_w1=True)['status'] == 'BLOCKED'
    # Chromium has no W1 reading: the W2 receipt alone admits it.
    croot = root_of(tmp_path / 'c')
    receipt(croot, 'r1', service=CR)
    cref = w2_record(tmp_path, name='cr.json', svc='playwright-mcp')
    before = w2_record(tmp_path, cid=OLD, mode='before', name='before.json', svc='playwright-mcp')
    assert adm.admit(croot, CR, w2={CR: {**cref, 'before': before}})['status'] == 'ADMITTED'
    # Without any recorded old id (no W1 at the failure, no before record), a new container cannot be shown.
    assert adm.admit(croot, CR, w2={CR: cref})['status'] == 'BLOCKED'


@pytest.mark.parametrize('fault', ['not_json', 'partial', 'list', 'sessions_list', 'bad_finished', 'bad_required',
                                   'symlink_receipt', 'symlink_run', 'missing_root'])
def test_malformed_earlier_receipt_blocks(tmp_path, fault):
    root = root_of(tmp_path)
    receipt(root, 'r0', recreation=False, finished='2026-10-23T08:00:00Z')
    folder = root / 'r1' / 'check'
    folder.mkdir(parents=True)
    body = {'not_json': b'{not json', 'partial': b'{"journey": "p3", "finished_at": "2026-10-2',
            'list': b'[1]', 'sessions_list': json.dumps({'journey': 'p3', 'finished_at': FAILED_AT,
                                                        'sessions': [WK]}).encode(),
            'bad_finished': json.dumps({'journey': 'p3', 'finished_at': '2026-10-24 08:00'}).encode(),
            'bad_required': json.dumps({'journey': 'p3', 'finished_at': FAILED_AT,
                                        'mcp_service_recreation_required': ['x']}).encode()}.get(fault)
    if body is not None:
        (folder / 'receipt.json').write_bytes(body)
    elif fault == 'symlink_receipt':
        (folder / 'receipt.json').symlink_to(root / 'r0' / 'check' / 'receipt.json')
    elif fault == 'symlink_run':
        os.rmdir(folder)
        os.rmdir(root / 'r1')
        (root / 'r1').symlink_to(root / 'r0')
    got = adm.admit(root / 'absent' if fault == 'missing_root' else root, WK, need_w1=True)
    assert got['status'] == 'BLOCKED' and got['reasons'], got


def test_newest_use_decides_and_unnamed_service_counts(tmp_path):
    root = root_of(tmp_path)
    receipt(root, 'r1')  # failed at 08:00
    receipt(root, 'r2', recreation=False, finished='2026-10-24T08:30:00Z')
    assert adm.admit(root, WK, need_w1=True)['status'] == 'ADMITTED'
    receipt(root, 'r3', recreation=False, finished='2026-10-24T09:30:00Z',
            mcp_service_recreation_required=[{'service': 'unknown MCP service for webkit', 'phase': 'x'}])
    assert adm.admit(root, WK, need_w1=True)['status'] == 'BLOCKED'
    assert adm.admit(root, CR)['status'] == 'ADMITTED'  # CR never used by those receipts


def test_profile_and_argument_shapes(tmp_path):
    good = {WK: {'path': '/abs/after.json', 'sha256': 'e' * 64}}
    assert adm.w2_problems(good) == []
    assert adm.w2_problems({WK: {'path': 'rel.json', 'sha256': 'e' * 64}})
    assert adm.w2_problems({WK: {'path': '/abs', 'sha256': 'E' * 64}})
    assert adm.w2_problems({'nohost': {'path': '/abs', 'sha256': 'e' * 64}})
    assert adm.w2_problems({WK: {'path': '/abs', 'sha256': 'e' * 64, 'override': True}})
    profile = p3.default_p3_profile()
    t, problems = p3.parse_p3_profile(json.dumps(profile))
    assert not problems and 'w2_recreation' not in t
    t, problems = p3.parse_p3_profile(json.dumps({**profile, 'w2_recreation': good}))
    assert not problems and t['w2_recreation'] == good
    assert p3.parse_p3_profile(json.dumps({**profile, 'w2_recreation': {WK: {}}}))[1]


# ---- 4c: Security N1, nothing between the terminal CLOSE result and browser_close raises ----

class Transport:
    def __init__(self):
        self.browser_closes = 0

    async def call_tool(self, name, args):
        assert not self.browser_closes, 'MCP call after browser_close'
        assert name == 'browser_close'
        self.browser_closes += 1
        return SimpleNamespace(content=[], isError=False)


def clean(names=('A', 'B'), log=None):
    return {'contexts': {n: {'error': None, 'page_created': True, 'page_closed': True,
                            'context_still_in_browser': False} for n in names},
            'other_contexts_left': 0, 'guard_page_closed': True, 'guard_context_closed': True,
            'journal': {'status': 'complete', 'reasons': []}, 'log': log if log is not None else {}}


def off_origin():
    return {'requests': [{'ctx': 'A', 't': 'fixed', 'method': 'GET', 'url': EXACT, 'type': 'fetch'}]}


MALFORMED = {
    'contexts_list': lambda d: d.update(contexts=['A', 'B']),
    'context_state_text': lambda d: d['contexts'].update(B='closed'),
    'context_errors_text': lambda d: d['contexts']['A'].update(errors='boom'),
    'error_without_step': lambda d: d['contexts']['A'].update(errors=[{'error': 'fixed'}]),
    'error_entry_text': lambda d: d['contexts']['A'].update(errors=['fixed']),
    'error_not_text': lambda d: d['contexts']['A'].update(error={'fixed': 1}),
    'top_errors_dict': lambda d: d.update(errors={'step': 'x'}),
    'top_error_without_step': lambda d: d.update(errors=[{'error': 'fixed'}]),
    'journal_text': lambda d: d.update(journal='complete'),
    'journal_reasons_text': lambda d: d['journal'].update(reasons='fixed'),
    'journal_reason_not_text': lambda d: d['journal'].update(reasons=[{'x': 1}]),
    'journal_missing': lambda d: d.pop('journal'),
    'left_text': lambda d: d.update(other_contexts_left='0'),
    'guard_flag_text': lambda d: d.update(guard_context_closed='true'),
    'page_closed_text': lambda d: d['contexts']['B'].update(page_closed='yes'),
    'log_list': lambda d: d.update(log=[EXACT]),
    'log_kind_text': lambda d: d['log'].update(requests='fixed'),
    'log_event_text': lambda d: d['log'].setdefault('requests', []).append('fixed'),
    'log_event_without_url': lambda d: d['log'].setdefault('requests', []).append({'ctx': 'A', 'method': 'GET'}),
    'log_missing': lambda d: d.pop('log'),
}


def run_cleanup(monkeypatch, result):
    # These cases are about the CLOSE result's shape, not context names: the fakes use two contexts
    monkeypatch.setitem(p3.ENGINES['chromium'], 'contexts', ('A', 'B'))
    s, r, latch = Transport(), p3.new_receipt('N1', None), g.StopLatch()
    r['origin'] = ORIGIN
    r['sessions']['chromium'] = {'url': CR}

    async def call(session, code):
        assert code == p3.CLOSE
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(p3, '_call', call)
    asyncio.run(p3.cleanup(s, r, 'chromium', 'N1', latch, ORIGIN))
    p3.finish(r, Path('/nonexistent-never-written'), persist=False)
    return s, r, latch


@pytest.mark.parametrize('fault', sorted(MALFORMED))
@pytest.mark.parametrize('w4', [False, True], ids=['blocked', 'off_origin'])
def test_malformed_close_result_is_incomplete_and_browser_close_still_runs(monkeypatch, fault, w4):
    d = clean(log=off_origin() if w4 else {})
    MALFORMED[fault](d)
    s, r, latch = run_cleanup(monkeypatch, d)
    c = r['cleanup']['chromium']
    assert s.browser_closes == 1 and c['browser_close'] == 'ok' and not c['confirmed']
    assert c['journal']['status'] == 'incomplete' and c['journal']['reasons']
    if w4 and fault not in ('log_list', 'log_kind_text', 'log_missing'):
        assert r['exit_code'] == 4 and r['verdict'] == 'W4 TRIPPED'
        assert [x['url'] for x in r['w4']['observations']] == [EXACT]
    else:
        assert r['exit_code'] == 3 and r['verdict'] == 'BLOCKED' and not r['w4']['observations']
    assert r['traffic_gate']['status'] != 'PASS'


@pytest.mark.parametrize('result', ['text', None, 7, ['A'], RuntimeError('fixed CLOSE failure')],
                         ids=['text', 'none', 'int', 'list', 'raised'])
def test_non_object_close_result_blocks_once(monkeypatch, result):
    s, r, latch = run_cleanup(monkeypatch, result)
    c = r['cleanup']['chromium']
    assert s.browser_closes == 1 and r['exit_code'] == 3 and not c['confirmed']
    assert c['journal']['status'] == 'incomplete'
    assert any(x.startswith('CLOSE') for x in c['errors'])


def test_clean_close_still_confirms_and_off_origin_still_trips(monkeypatch):
    s, r, latch = run_cleanup(monkeypatch, clean())
    c = r['cleanup']['chromium']
    assert s.browser_closes == 1 and c['confirmed'] and c['journal']['status'] == 'complete' and not c['errors']
    assert not latch.stopped and not r.get('malformed_logs')
    s, r, latch = run_cleanup(monkeypatch, clean(log=off_origin()))
    assert s.browser_closes == 1 and r['cleanup']['chromium']['confirmed'] and r['exit_code'] == 4
    assert [x['url'] for x in r['w4']['observations']] == [EXACT]
