"""#125 stages 4b (W1 admission refusal) and 4c (Security N1 total CLOSE reader): fixed fakes only.

No browser, MCP service, network, docker or host action: open_session is replaced by a counter that fails the
test if it is ever entered, and every receipt and W2 record is a fixed file under tmp_path.
"""
import asyncio
import contextlib
import datetime
import hashlib
import importlib.util
import json
import os
import socket
import stat
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
    if service == WK and w1:  # the earlier run's checked W1 before-reading (DECISION-11)
        d['w1'] = {'service': WK, 'status': 'PROVISIONAL',
                   'before': {'path': '/fixed/earlier-before.json', 'sha256': 'e' * 64, 'id': w1}}
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


def w1(cid=NEW, started=NEW_START, running=True):
    """The checked W1 before-reading as the receipt's w1.before holds it (DECISION-11, first_app_p3_w1.gate)."""
    return {'path': '/fixed/w1-before.json', 'sha256': 'f' * 64, 'id': cid, 'image': p3.hc.ENGINE_PIN,
            'started_at': started, 'restart_count': 0, 'running': running, 'paused': False, 'restarting': False,
            'networks': ['temper-ai_default'], 'taken_at': '2026-10-24T09:00:30.000000Z'}


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
    assert got['w2']['w1_before'] == {'id': NEW, 'started_at': NEW_START, 'path': '/fixed/w1-before.json',
                                      'sha256': 'f' * 64}
    # DECISION-11 rule 4: the checked before-reading must be that container: missing, other id, other start, not
    # running or no full id -> no.
    for bad in (None, w1(cid='d' * 64), w1(started='2026-10-24T09:00:00.123457Z'), w1(running=False),
                w1(cid='b' * 12)):
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


# ---- #279 (Security #105 A6): a started marker before the first MCP call, held by admission ----
# Hypothesis H-279-A6 (/home/shinelay/architecture-dept/reviews/p3-security-105-fixes/HYPOTHESES.md).

MARKER = 'started.json'  # the contract name, written out here so a missing marker fails on behaviour
MARKED_AT = '2026-10-24T08:00:00.000+00:00'
MARKED_NS = int(datetime.datetime(2026, 10, 24, 8, tzinfo=datetime.UTC).timestamp()) * 1_000_000_000
PHASES = {CR: ['chromium:pins-chromium-copy', 'chromium:pins-webkit-copy', 'chromium'], WK: ['webkit:probe', 'webkit']}


def marker(root, run, *, at=MARKED_AT, case=None, services=None, body=None, receipt_too=None):
    """A unit folder holding the driver's started marker and, when asked, its final receipt (recreation or not)."""
    folder = root / run / 'check' / (case or '')
    folder.mkdir(parents=True, exist_ok=True)
    data = {'journey': 'p3', 'marker': 'started', 'label': 'fixed', 'started_at': at,
            'services': PHASES if services is None else services, 'receipt': str(folder / 'receipt.json'),
            'rule': 'fixed'}
    (folder / MARKER).write_bytes(json.dumps(data).encode() if body is None else body)
    os.utime(folder / MARKER, ns=(MARKED_NS, MARKED_NS))
    if receipt_too is not None:
        receipt(root, run, service=CR, finished='2026-10-24T08:10:00Z', recreation=receipt_too, case=case)
    return folder / MARKER


def cr_w2(tmp_path):
    """Ops' W2 for the Chromium service: a container started 09:00 (after the 08:00 marker), before record 09:01."""
    after = w2_record(tmp_path, name='cr-after.json', svc='playwright-mcp')
    return {CR: {**after, 'before': w2_record(tmp_path, cid=OLD, mode='before', name='cr-before.json',
                                             svc='playwright-mcp')}}


def full_target(root):
    t, problems = p3.parse_p3_profile(json.dumps(p3.default_p3_profile()))
    assert not problems
    t.update(receipts_root=str(root), receipts_out_name='check')
    return t


def test_a6_marker_is_written_before_the_first_mcp_call(tmp_path, monkeypatch):
    root = root_of(tmp_path)
    out = root / 'run1' / 'check'
    order = []

    class Session:  # a fake MCP that records each call and whether the marker existed at that moment
        def __init__(self, url):
            self.url = url

        async def initialize(self):
            order.append(('initialize', self.url, (out / MARKER).is_file()))

        async def call_tool(self, name, args):
            order.append((name, self.url, (out / MARKER).is_file()))
            return SimpleNamespace(content=[], isError=False)

    @contextlib.asynccontextmanager
    async def session(url):
        order.append(('open', url, (out / MARKER).is_file()))
        yield Session(url)

    async def call(s, code):
        order.append(('code', s.url, (out / MARKER).is_file()))
        return {'error': 'fixed fake browser: nothing served'}

    monkeypatch.setattr(p3, 'open_session', session)
    monkeypatch.setattr(p3, '_call', call)
    r = asyncio.run(p3.check_target(CR, WK, full_target(root), out, 'A6', 900, latch=g.StopLatch(), persist=False,
                                    receipt=p3.new_receipt('A6', None)))
    assert order and order[0] == ('open', CR, True), order
    assert all(seen for _, _, seen in order), order
    m = out / MARKER
    assert stat.S_ISREG(m.lstat().st_mode) and stat.S_IMODE(m.stat().st_mode) == 0o600
    data = json.loads(m.read_text())
    assert data['journey'] == 'p3' and data['marker'] == 'started' and data['services'] == PHASES
    assert r['started_marker']['path'] == str(m) and r['browser_contact']
    # Killed at this point = a marker and no receipt: the next admission holds both services.
    assert not (out / 'receipt.json').exists()
    assert adm.admit(root, CR)['status'] == 'BLOCKED' and adm.admit(root, WK, need_w1=True)['status'] == 'BLOCKED'


def test_a6_marker_without_receipt_holds_its_services_and_makes_no_mcp_call(tmp_path, mcp_calls):
    root = root_of(tmp_path)
    m = marker(root, 'r1', case='P3-CLEAN')
    got = adm.admit(root, CR)
    assert got['status'] == 'BLOCKED' and got['recreation_required'], got
    assert got['newest_use'] == [str(m)] and got['unfinished_markers'] == [str(m)]
    assert 'no final receipt.json' in got['reasons'][0] and 'no Ops W2 recreation receipt' in got['reasons'][0]
    assert adm.admit(root, WK, need_w1=True)['status'] == 'BLOCKED'
    assert adm.admit(root, 'http://other-mcp:8931/mcp')['status'] == 'ADMITTED'  # a service it does not name
    out = tmp_path / 'out'
    r = asyncio.run(p3.check_target(CR, WK, full_target(root), out, 'R', 900, latch=g.StopLatch(), persist=False,
                                    receipt=p3.new_receipt('R', None)))
    assert mcp_calls == [] and r['verdict'] == 'BLOCKED' and r['exit_code'] == 3
    assert r['admission'][CR]['status'] == 'BLOCKED' and 'no MCP call' in r['runner_error']
    assert not (out / MARKER).exists()  # refused before the marker: nothing was about to be contacted


def test_a6_only_w2_newer_than_the_marker_or_a_later_receipt_lets_the_service_in(tmp_path):
    root = root_of(tmp_path)
    marker(root, 'r1')
    got = adm.admit(root, CR, w2=cr_w2(tmp_path))
    assert got['status'] == 'ADMITTED' and got['recreation_required'] and got['w2']['after']['container_id'] == NEW
    late = root_of(tmp_path / 'late')
    marker(late, 'r1', at='2026-10-24T09:30:00Z')  # the W2 container started before this marker
    got = adm.admit(late, CR, w2=cr_w2(tmp_path / 'late'))
    assert got['status'] == 'BLOCKED' and 'is not later than' in got['reasons'][0], got
    assert 'started_at 2026-10-24T09:30:00Z' in got['reasons'][0]
    # A later P3 receipt that used the service is the newest use: the marker no longer decides.
    receipt(root, 'r2', service=CR, finished='2026-10-24T09:10:00Z', recreation=False)
    assert adm.admit(root, CR)['status'] == 'ADMITTED'


def test_a6_marker_beside_its_receipt_is_the_receipts_business(tmp_path):
    root = root_of(tmp_path)
    marker(root, 'r1', receipt_too=False)
    got = adm.admit(root, CR)
    assert got['status'] == 'ADMITTED' and not got['recreation_required'] and got['p3_receipts'] == 1
    assert got.get('unfinished_markers', []) == []
    held = root_of(tmp_path / 'held')
    marker(held, 'r1', receipt_too=True)  # the receipt itself lists recreation: it decides, as before
    got = adm.admit(held, CR)
    assert got['status'] == 'BLOCKED' and 'lists mcp_service_recreation_required' in got['reasons'][0]


BAD_MARKERS = {
    'not_json': b'{not json', 'empty': b'', 'list': b'[1]',
    'other_journey': json.dumps({'journey': 'shared', 'marker': 'started', 'started_at': MARKED_AT,
                                 'services': PHASES}).encode(),
    'not_started': json.dumps({'journey': 'p3', 'marker': 'done', 'started_at': MARKED_AT,
                               'services': PHASES}).encode(),
    'no_services': json.dumps({'journey': 'p3', 'marker': 'started', 'started_at': MARKED_AT}).encode(),
    'empty_services': json.dumps({'journey': 'p3', 'marker': 'started', 'started_at': MARKED_AT,
                                  'services': {}}).encode(),
    'service_not_url': json.dumps({'journey': 'p3', 'marker': 'started', 'started_at': MARKED_AT,
                                   'services': {'playwright-mcp': ['chromium']}}).encode(),
    'phases_text': json.dumps({'journey': 'p3', 'marker': 'started', 'started_at': MARKED_AT,
                               'services': {CR: 'chromium'}}).encode(),
    'bad_started_at': json.dumps({'journey': 'p3', 'marker': 'started', 'started_at': '2026-10-24 08:00',
                                  'services': PHASES}).encode(),
}


@pytest.mark.parametrize('fault', sorted(BAD_MARKERS) + ['symlink', 'directory'])
def test_a6_malformed_marker_fails_closed_never_unused(tmp_path, fault):
    root = root_of(tmp_path)
    if fault in BAD_MARKERS:
        marker(root, 'r1', body=BAD_MARKERS[fault])
    else:
        folder = root / 'r1' / 'check'
        folder.mkdir(parents=True)
        if fault == 'symlink':
            (tmp_path / 'elsewhere.json').write_text(json.dumps({'journey': 'p3'}))
            (folder / MARKER).symlink_to(tmp_path / 'elsewhere.json')
        else:
            (folder / MARKER).mkdir()
    for url in (CR, WK, 'http://other-mcp:8931/mcp'):
        got = adm.admit(root, url, need_w1=url == WK)
        assert got['status'] == 'BLOCKED' and got['reasons'], (url, got)
    got = adm.admit(root, CR, w2=cr_w2(tmp_path))
    if fault in BAD_MARKERS:
        # Held, not ignored: every service needs W2 recreation newer than the file's modification time.
        assert got['status'] == 'ADMITTED' and got['recreation_required'], got
        blocked = adm.admit(root, CR)
        assert 'malformed started marker' in blocked['reasons'][0] and 'modification time' not in blocked['reasons'][0]
        os.utime(root / 'r1' / 'check' / MARKER, ns=(MARKED_NS + 2 * 3600 * 10 ** 9,) * 2)  # 10:00, after W2
        late = adm.admit(root, CR, w2=cr_w2(tmp_path))
        assert late['status'] == 'BLOCKED' and 'modification time' in late['reasons'][0], late
    else:
        assert got['status'] == 'BLOCKED' and 'not a regular file' in got['reasons'][0], got


def test_a6_the_units_own_marker_is_not_an_earlier_run(tmp_path):
    root = root_of(tmp_path)
    own = marker(root, 'r1', case='P3-CLEAN')
    got = adm.admit(root, WK, need_w1=True, own_marker=str(own))
    assert got['status'] == 'ADMITTED' and got['unfinished_markers'] == [] and got['own_marker'] == str(own)
    assert adm.admit(root, WK, need_w1=True)['status'] == 'BLOCKED'
    marker(root, 'r0')  # an earlier unit that ended without a receipt is still held
    assert adm.admit(root, WK, need_w1=True, own_marker=str(own))['status'] == 'BLOCKED'
    assert adm.STARTED_MARKER == MARKER
