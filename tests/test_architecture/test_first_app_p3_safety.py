"""#129 source-boundary stage: fixed files, EventEmitters and fake transports only; never qualification."""
import asyncio
import base64
import contextlib
import importlib.util
import json
import os
import socket
import stat
import subprocess
import sys
import threading
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
ORIGIN = 'http://100.110.162.4:8962'
EXACT = 'https://outside.invalid/a?' + 'long=abcdef&' * 150 + 'literal=%22%3C%26&end=last'
NODE = Path(__file__).parent / 'fixtures/p3_fake_browser.cjs'


@pytest.fixture(autouse=True)
def forbid_real_operations(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError('source-only tests must never connect/start a real service')

    @contextlib.asynccontextmanager
    async def no_session(*a, **kw):
        forbidden()
        yield

    monkeypatch.setattr(p3, 'open_session', no_session)
    monkeypatch.setattr(p3.http.server, 'ThreadingHTTPServer', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(p3.fs, 'serve_ip', lambda *a: '100.110.162.4')


def target():
    raw = g.snapshot(p3.FIXTURE, p3.CTYPES)
    t, problems = p3.parse_p3_profile(json.dumps(p3.default_p3_profile(
        pins={n: p3.fac.sha256(b) for n, b in raw.items()})))
    assert not problems
    return t


def node_case(code, engine='chromium', **kw):
    payload = dict(code=code, engine=engine, files={n: b.decode() for n, b in g.snapshot(p3.FIXTURE, p3.CTYPES).items()},
                   ctypes=p3.CTYPES, close=p3.CLOSE, url=EXACT, **kw)
    proc = subprocess.run(['node', str(NODE)], input=json.dumps(payload), text=True,
                          capture_output=True, timeout=10)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def clean_close(names, log=None):
    return {'contexts': {n: {'error': None, 'page_created': True, 'page_closed': True,
                            'context_still_in_browser': False} for n in names},
            'other_contexts_left': 0, 'log': log or {}}


def event(url=EXACT):
    return {'requests': [{'ctx': 'fake', 't': 'fixed', 'method': 'GET', 'url': url,
                          'type': 'script', 'navigation': False}]}


def passing(r):
    rows = p3.p3_rows(p3.KIT_WORDING, p3.USERS)
    r.update(pins={'ok': True}, reach={},
             steps=[dict(x, kind='host' if x.get('host') else 'browser', status='PASS', traffic=[], reasons=[], notes=[])
                    for x in rows], steps_attempted=len(rows),
             sessions={e: {'status': 'RAN', 'before_first_navigation': True} for e in p3.ENGINES},
             cleanup={e: {'confirmed': True} for e in p3.ENGINES},
             screenshots=[{'after': k, 'file': 'fake.png'} for k in p3.SHOTS])
    return r


# Happy paths first, then the exact faults in the same event/lifetime boundaries.
@pytest.mark.parametrize('engine', ['chromium', 'webkit'])
@pytest.mark.parametrize('kind', ['setup', 'pins', 'down', 'engine'])
def test_generated_contexts_block_sw_and_observe_before_navigation(engine, kind):
    js = p3.setup_js(target(), engine) if kind == 'setup' else p3.probe_js(target(), kind, engine)
    data = node_case(js, engine)
    assert not data['error'] and not data['close_error']
    assert all(o['serviceWorkers'] == 'block' for o in data['options'])
    assert len(data['options']) == (2 if kind == 'setup' else 1)
    assert data['contexts_left'] == 0
    if kind != 'setup':
        assert data['result']['closed'] and data['result']['observers_at']
        assert data['result']['log']['requests'] == []


@pytest.mark.parametrize(('kind', 'phase'), [(kind, phase) for kind in ['pins', 'down', 'engine']
                                            for phase in ['newPage', 'goto', 'close']
                                            if (kind, phase) != ('engine', 'goto')])
def test_probe_event_witnesses_and_sw_failures_survive_terminal_paths(kind, phase):
    data = node_case(p3.probe_js(target(), kind), at=phase,
                     fault='navigation' if phase == 'goto' else '')
    result = data['result']
    log = result['log']
    assert log['requests'][0]['url'] == EXACT and log['failed'][0]['url'] == EXACT
    assert log['responses'][0]['url'] == EXACT and log['serviceworkers'][0]['url'] == EXACT
    assert 'registration' in log['pageerrors'][0]['message'] and log['console']
    assert log['websockets'][0]['url'] == EXACT
    if phase == 'goto':
        assert result['error'] == 'net::ERR_FIXED_NAVIGATION'
    if kind == 'pins' and phase != 'goto':
        assert result['root']['b64'] and result['files']['app.js']['b64']
    assert result['closed'] and data['contexts_left'] == 0


@pytest.mark.parametrize('fail_at', [1, 2])
def test_partial_setup_tracks_context_even_without_page_and_disposes(fail_at):
    data = node_case(p3.setup_js(target(), 'chromium'), fault='newPage', failAt=fail_at, at='newPage')
    assert data['error'] and 'newPage' in data['error']
    assert len(data['tracked']) == fail_at and data['contexts_left'] == 0
    assert len(data['close_result']['contexts']) == fail_at
    assert not list(data['close_result']['contexts'].values())[-1]['page_created']
    assert data['close_result']['log']['requests'][0]['url'] == EXACT


def test_js_close_failure_retains_final_events_not_just_route_or_dom_refs():
    data = node_case(p3.probe_js(target(), 'pins'), fault='close', at='close')
    assert data['result']['files']['app.js']['b64'] and not data['result']['closed']
    assert data['result']['log']['requests'][0]['url'] == EXACT
    assert data['close_result']['log']['requests'][0]['url'] == EXACT
    assert data['contexts_left'] == 1


def test_sticky_w4_exact_events_and_same_origin_are_distinct(tmp_path):
    latch = g.StopLatch()
    r = passing(p3.new_receipt('fake', target()))
    for url in [ORIGIN + '/unexpected?x=1', 'ws://100.110.162.4:8962/channel']:
        p3.collect(r, event(url), ORIGIN, latch, 'same-origin')
    assert not latch.stopped and p3.final_verdict(r)[0] == 'FAIL'
    p3.collect(r, event(), ORIGIN, latch, 'late-close')
    assert latch.tripped and p3.final_verdict(r)[0] == 'W4 TRIPPED'
    latch.observe(r, {}, ORIGIN, 'later-clean-case')
    p3.finish(r, tmp_path)
    assert r['exit_code'] == 4 and r['w4']['observations'][0]['url'] == EXACT
    for name in ['receipt.json', 'observations.json', 'summary.md']:
        f = tmp_path / name
        assert stat.S_ISREG(f.lstat().st_mode) and stat.S_IMODE(f.stat().st_mode) == 0o600
        assert EXACT in f.read_text()
    assert json.loads((tmp_path / 'observations.json').read_text())['requests'][-1]['url'] == EXACT
    hold = r['w4']['operator_hold']
    assert 'queue_blocked' in hold and 'Only Security' in hold and 'CLI invocation' in hold


@pytest.mark.parametrize('kind', ['requests', 'responses', 'failed', 'websockets', 'serviceworkers', 'popups'])
def test_w4_all_observed_destinations_no_expected_exception_list(kind):
    latch = g.StopLatch()
    latch.observe({}, {kind: [{'url': EXACT}]}, ORIGIN, kind)
    assert latch.tripped and latch.observations[0]['url'] == EXACT
    latch.bind({})
    assert latch.tripped
    # DOM references and abort-route descriptions are not independent event witnesses.
    control = g.StopLatch()
    control.observe({}, {'refs': [EXACT], 'api_blocked': [{'url': EXACT}]}, ORIGIN, 'not-witnesses')
    assert not control.stopped


@pytest.mark.parametrize(('verdict', 'code'), [('PASS', 0), ('FAIL', 1), ('BLOCKED', 3),
                                               ('REFUSED', 2), ('W4 TRIPPED', 4)])
def test_p3_exit_codes_reserve_four_for_w4_and_leave_blocked_and_legacy_unchanged(verdict, code):
    assert p3.exit_status({'verdict': verdict}) == code
    assert p3.fac.EXIT == {'PASS': 0, 'FAIL': 1, 'REFUSED': 2, 'BLOCKED': 3}


@pytest.mark.parametrize(('origin', 'url', 'outside'), [
    ('http://fixture.invalid', 'http://fixture.invalid:80/a', False),
    ('https://fixture.invalid', 'https://fixture.invalid:443/a', False),
    ('http://fixture.invalid:80', 'ws://fixture.invalid/a', False),
    ('https://fixture.invalid:443', 'wss://fixture.invalid/a', False),
    ('http://fixture.invalid', 'http://fixture.invalid:0/a', True),
    ('https://fixture.invalid', 'https://fixture.invalid:0/a', True),
    ('http://fixture.invalid:80', 'ws://fixture.invalid:81/a', True),
    ('https://fixture.invalid:443', 'wss://fixture.invalid:444/a', True),
])
def test_w4_origin_defaults_never_exempt_an_explicit_different_port(origin, url, outside):
    latch = g.StopLatch()
    latch.observe({}, event(url), origin, 'fixed-origin')
    assert latch.tripped == outside and not latch.blocked
    assert [x['url'] for x in latch.observations] == ([url] if outside else [])


class FakeTransport:
    def __init__(self, kind, fail_close=False):
        self.kind = kind
        self.browser_closes = 0
        self.fail_close = fail_close

    async def initialize(self):
        pass

    async def call_tool(self, name, args):
        assert name == 'browser_close'
        self.browser_closes += 1
        if self.fail_close:
            raise RuntimeError('fixed browser fallback failure')
        return SimpleNamespace(content=[], isError=False)


@pytest.mark.parametrize('fault', ['clean', 'CLOSE', 'DRAIN', 'browser_close', 'partial_setup'])
def test_independent_browser_fallback_even_after_close_or_partial_setup_fault(monkeypatch, fault):
    s = FakeTransport('chromium', fail_close=fault == 'browser_close')
    r, latch = p3.new_receipt('fake', target()), g.StopLatch()

    async def call(session, code):
        if code == p3.CLOSE:
            if fault == 'CLOSE':
                raise RuntimeError('fixed CLOSE failure')
            return clean_close(['A'] if fault == 'partial_setup' else ['A', 'B'], event())
        assert code == p3.DRAIN
        if fault == 'DRAIN':
            raise RuntimeError('fixed terminal observation failure')
        return event(ORIGIN + '/')

    monkeypatch.setattr(p3, '_call', call)
    asyncio.run(p3.cleanup(s, r, 'chromium', 'fake', latch))
    assert s.browser_closes == 1
    assert r['cleanup']['chromium']['confirmed'] == (fault == 'clean')
    assert latch.blocked == (fault != 'clean')
    if fault != 'CLOSE':
        assert r['log']['requests'][0]['url'] == EXACT and latch.tripped


def install_journey(monkeypatch, fault='clean'):
    sessions, kinds = [], iter(['pins', 'chromium', 'engine', 'webkit'])
    t = target()
    raw = g.snapshot(p3.FIXTURE, p3.CTYPES)

    @contextlib.asynccontextmanager
    async def open_fake(url):
        s = FakeTransport(next(kinds))
        sessions.append(s)
        yield s
        if fault == 'transport_exit' and s.kind == 'pins':
            raise RuntimeError('fixed transport exit after pin data')

    async def call(s, code):
        if code == p3.CLOSE:
            if fault == 'CLOSE' and s.kind == 'chromium':
                raise RuntimeError('fixed CLOSE failure')
            names = [s.kind] if s.kind in ('pins', 'engine') else list(p3.ENGINES[s.kind]['contexts'])
            if s.kind in ('pins', 'engine'):
                names = ['probe']
            return clean_close(names, event() if fault == 'late_close' and s.kind == 'chromium' else {})
        if code == p3.DRAIN:
            return event() if fault == 'late_drain' and s.kind == 'chromium' else {}
        assert s.kind in ('pins', 'engine')
        if s.kind == 'engine':
            return {'type': 'webkit', 'version': 'fake-1', 'log': {}}
        files = {n: {'status': 200, 'content_type': p3.CTYPES[n], 'url': ORIGIN + '/' + n,
                     'b64': base64.b64encode(b).decode()} for n, b in raw.items()}
        if fault == 'bad_pin':
            files['app.js']['b64'] = base64.b64encode(b'not the reviewed file').decode()
        return {'status': 200, 'closed': True, 'final_url': ORIGIN + '/', 'root': files['index.html'],
                'files': files, 'log': event() if fault in ('stage_A', 'bad_pin', 'transport_exit') else {}}

    async def rows(s, r, engine, rowlist, target, out, label, host_dir, deadline, hooks, browser_url, cached, latch):
        assert not latch.stopped
        r['sessions'][engine].update(status='RAN', before_first_navigation=True)
        r['steps'].extend(dict(x, kind='host' if x.get('host') else 'browser', status='PASS',
                               traffic=[], reasons=[], notes=[]) for x in rowlist)
        r.setdefault('screenshots', []).extend({'after': k, 'file': 'fake.png'} for k in p3.SHOTS
                                               if (k.startswith('W-')) == (engine == 'webkit'))
        if fault == 'partial_setup':
            raise RuntimeError('newPage failed after context creation')
        return True  # regression: the pending True must not defeat a late final drain

    monkeypatch.setattr(p3, 'open_session', open_fake)
    monkeypatch.setattr(p3, '_call', call)
    monkeypatch.setattr(p3, '_section_rows', rows)
    return t, sessions


@pytest.mark.parametrize('fault', ['clean', 'stage_A', 'bad_pin', 'transport_exit', 'late_drain', 'late_close',
                                   'CLOSE', 'partial_setup'])
def test_journey_waits_for_terminal_traffic_and_disposal_before_next_engine(monkeypatch, tmp_path, fault):
    t, sessions = install_journey(monkeypatch, fault)
    latch = g.StopLatch()
    r = asyncio.run(p3.check_target('fake:chromium', 'fake:webkit', t, tmp_path, 'fake', tmp_path / 'host', 900,
                                     latch=latch))
    assert all(s.browser_closes == 1 for s in sessions)
    if fault == 'clean':
        assert r['verdict'] == 'PASS' and r['exit_code'] == 0 and len(sessions) == 4 and not latch.stopped
    elif fault in ('stage_A', 'bad_pin', 'transport_exit', 'late_drain', 'late_close'):
        assert r['verdict'] == 'W4 TRIPPED' and r['exit_code'] == 4 and latch.tripped
        assert len(sessions) == (1 if fault in ('stage_A', 'bad_pin', 'transport_exit') else 2)
        assert EXACT in (tmp_path / 'observations.json').read_text()
        assert r['probes']['stage-A']['files']['app.js']['b64']  # pin/error evidence survives too
    else:
        assert r['verdict'] == 'BLOCKED' and len(sessions) == 2 and latch.blocked


@pytest.mark.parametrize('fault', ['clean', 'off_origin', 'error'])
def test_down_probe_keeps_observations_through_transport_error(monkeypatch, fault):
    s, r, latch = FakeTransport('probe'), p3.new_receipt('fake', target()), g.StopLatch()

    @contextlib.asynccontextmanager
    async def transport(url):
        yield s
        if fault == 'error':
            raise RuntimeError('fixed terminal transport error')

    async def call(session, code):
        if code == p3.CLOSE:
            return clean_close(['probe'])
        if code == p3.DRAIN:
            return {}
        return {'down': True, 'error': 'net::ERR_CONNECTION_REFUSED',
                'log': event(ORIGIN + '/' if fault == 'clean' else EXACT)}

    monkeypatch.setattr(p3, 'open_session', transport)
    monkeypatch.setattr(p3, '_call', call)
    got = asyncio.run(p3.probe_session('fake:', p3.probe_js(target(), 'down'), r=r, latch=latch, phase='down'))
    assert got['down'] and r['probes']['down']['down'] and s.browser_closes == 1
    assert r['log']['requests'][0]['url'] == (ORIGIN + '/' if fault == 'clean' else EXACT)
    assert latch.stopped == (fault != 'clean')


@pytest.mark.parametrize('fault', ['clean', 'W4', 'cleanup', 'NOT RUN', 'unmatched', 'empty', 'none', 'subset'])
def test_batch_invocation_latch_and_incomplete_selections(monkeypatch, tmp_path, fault):
    cases = [dict(case=n, expect=('PASS', None)) for n in ['CLEAN', 'SECOND']]
    calls = []

    async def control(args, case, out, tmp, ip, latch):
        assert not latch.stopped
        calls.append(case['case'])
        if fault == 'W4':
            latch.observe({}, event(), ORIGIN, 'close')
        elif fault == 'cleanup':
            latch.block('cleanup unresolved')
        return {'case': case['case'], 'status': 'NOT RUN' if fault == 'NOT RUN' else 'OK'}

    monkeypatch.setattr(p3, 'CONTROLS', [] if fault == 'none' else cases)
    monkeypatch.setattr(p3, 'run_control', control)
    only = {'unmatched': 'MISSING', 'empty': ', ,', 'subset': 'CLEAN'}.get(fault, '')
    args = SimpleNamespace(only=only, browser='fake:', serve_ip='100.110.162.4')
    code = asyncio.run(p3.controls(args, tmp_path))
    data = json.loads((tmp_path / 'controls.json').read_text())
    assert code == (4 if fault == 'W4' else 0 if fault in ('clean', 'subset') else 1)
    assert data['all_ok'] == (fault in ('clean', 'subset'))
    assert data['full_qualification'] == (fault == 'clean')
    if fault in ('W4', 'cleanup'):
        assert calls == ['CLEAN'] and data['not_reached'] == ['SECOND']
    if fault in ('unmatched', 'empty', 'none'):
        assert calls == [] and data['selection_error']
    assert stat.S_IMODE((tmp_path / 'controls.json').stat().st_mode) == 0o600


def test_clean_materialization_variants_captured_pins_and_literal_serve_map(tmp_path):
    source = g.snapshot(p3.FIXTURE, p3.CTYPES)
    route_map = {'/': 'index.html', '/index.html': 'index.html', '/style.css': 'style.css',
                 '/app.js': 'app.js', '/favicon.svg': 'favicon.svg'}
    assert {url: v[0] for url, v in p3.fs.STATIC.items()} == route_map
    for variant in {c['variant'] for c in p3.CONTROLS}:
        site = p3.materialize(variant, tmp_path / variant)
        got = g.snapshot(site, p3.CTYPES)
        assert got == dict(source, **{'app.js': source['app.js'].replace(
            b'const VARIANT = "clean";', f'const VARIANT = {json.dumps(variant)};'.encode())})
    server = p3.P3Server(site, tmp_path / 'data')
    before = dict(server.files)
    (site / 'index.html').unlink()
    (site / 'index.html').symlink_to('/nonexistent-outside-fixture')
    (site / 'app.js').write_bytes(b'substituted after verified capture')
    sent = []
    handler = object.__new__(p3.P3Handler)
    handler.server = server
    handler._send = lambda code, body, ctype: sent.append((code, body))
    for route, name in route_map.items():
        handler.path = route
        handler.do_GET()
        assert sent[-1] == (200, before[name])
    for route in ['/index.html?x=1', '/%69ndex.html', '/x/../index.html']:
        handler.path = route
        handler.do_GET()
        assert sent[-1][0] == 404
    assert server.files == before  # pins are derived from this exact same captured mapping


@pytest.mark.parametrize('fault', ['leaf_link', 'parent_link', 'fifo', 'replacement'])
def test_fixture_snapshot_rejects_links_nonregular_and_substitution(monkeypatch, tmp_path, fault):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'a').write_bytes(b'verified')
    if fault == 'leaf_link':
        (source / 'a').unlink()
        (source / 'a').symlink_to(tmp_path / 'outside')
    elif fault == 'parent_link':
        alias = tmp_path / 'alias'
        alias.symlink_to(source, target_is_directory=True)
        source = alias
    elif fault == 'fifo':
        (source / 'a').unlink()
        os.mkfifo(source / 'a')
    else:
        original = os.read
        changed = False

        def swap(fd, size):
            nonlocal changed
            data = original(fd, size)
            if not changed:
                changed = True
                (source / 'replacement').write_bytes(b'outside')
                (source / 'replacement').replace(source / 'a')
            return data
        monkeypatch.setattr(g.os, 'read', swap)
    with pytest.raises((OSError, ValueError)):
        g.snapshot(source, ['a'])


@pytest.mark.parametrize('parent', [False, True])
def test_private_output_never_follows_links_or_overwrites(tmp_path, parent):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'receipt.json').write_text('unchanged')
    if parent:
        dest = tmp_path / 'alias'
        dest.symlink_to(outside, target_is_directory=True)
        path = dest / 'receipt.json'
    else:
        path = tmp_path / 'receipt.json'
        path.symlink_to(outside / 'receipt.json')
    with pytest.raises(OSError):
        g.write_json(path, {'bad': 'not written'})
    assert (outside / 'receipt.json').read_text() == 'unchanged'
    g.write_private(tmp_path / 'regular', 'first')
    with pytest.raises(FileExistsError):
        g.write_private(tmp_path / 'regular', 'second')
    assert (tmp_path / 'regular').read_text() == 'first'


@pytest.mark.parametrize('fault', ['clean', 'start', 'host', 'cancel', 'shutdown'])
def test_control_lifetime_always_stops_server_and_blocks_unresolved(monkeypatch, tmp_path, fault):
    seen = []

    class FakeServer:
        port, hits, starts = 8962, [], 1

        def __init__(self, site, data, variant, *, bind_address):
            assert bind_address == '0.0.0.0'  # container control caller retains its explicit existing bind
            self.files = g.snapshot(site, p3.CTYPES)
            seen.append('create')

        def start(self):
            seen.append('start')
            if fault == 'start':
                raise RuntimeError('fixed partial start failure')

        def retire(self):
            seen.append('retire')

        def shutdown(self):
            seen.append('shutdown')
            if fault == 'shutdown':
                raise RuntimeError('fixed shutdown failure')

    async def host(*a):
        if fault == 'host':
            raise RuntimeError('fixed host exception')
        await asyncio.Future()

    async def check(*a, **kw):
        await asyncio.sleep(0)  # let the fake host fail before disposal, if selected
        if fault == 'cancel':
            raise asyncio.CancelledError
        return passing(kw['receipt'])

    monkeypatch.setattr(p3, 'P3Server', FakeServer)
    monkeypatch.setattr(p3, 'control_host', host)
    monkeypatch.setattr(p3, 'check_target', check)
    case = dict(case='FAKE', variant='clean', expect=('PASS', None))
    args = SimpleNamespace(browser='fake:', browser_webkit='fake:')
    latch = g.StopLatch()
    invocation = p3.run_control(args, case, tmp_path / 'out', tmp_path / 'tmp', '100.110.162.4', latch)
    if fault == 'cancel':
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(invocation)
    else:
        result = asyncio.run(invocation)
        assert result['status'] == ('OK' if fault == 'clean' else 'BLOCKED')
    assert seen.count('shutdown') == 1 and seen.index('retire') < seen.index('shutdown')
    assert latch.stopped == (fault != 'clean')
    receipt = json.loads((tmp_path / 'out/FAKE/receipt.json').read_text())
    assert receipt['verdict'] == ('PASS' if fault == 'clean' else 'BLOCKED')


def test_threaded_host_action_cannot_restart_after_retirement(monkeypatch, tmp_path):
    site = p3.materialize('clean', tmp_path / 'fixture')
    server = p3.P3Server(site, tmp_path / 'data')
    entered, release = threading.Event(), threading.Event()
    results = []

    def action(self, kind):
        entered.set()
        assert release.wait(2)
        try:
            self.start()  # the real P3 boundary refuses before any socket/server operation
        except RuntimeError:
            return {'action': kind, 'done': False}
        raise AssertionError('retired server restarted')

    monkeypatch.setattr(p3.fs.SyntheticServer, 'host_action', action)
    thread = threading.Thread(target=lambda: results.append(server.host_action('restart')))
    thread.start()
    assert entered.wait(2)
    server.retire()
    release.set()
    server.shutdown()
    thread.join(2)
    assert not thread.is_alive() and results[0]['done'] is False
    assert server.host_action('start')['done'] is False
    with pytest.raises(RuntimeError, match='retired'):
        server.start()


@pytest.mark.parametrize('bind_address', [None, '0.0.0.0', '127.0.0.1'])
def test_server_partial_thread_start_owns_and_closes_resource(monkeypatch, tmp_path, bind_address):
    site = p3.materialize('clean', tmp_path / 'fixture')
    kw = {} if bind_address is None else {'bind_address': bind_address}
    server = p3.P3Server(site, tmp_path / 'data', **kw)
    want_address = '0.0.0.0' if bind_address is None else bind_address
    assert server.bind_address == want_address
    closed, bindings = [], []
    dummy = SimpleNamespace(server_address=('fake', 8962), server_close=lambda: closed.append('closed'),
                            serve_forever=lambda: None)

    def fake_http(address, handler):
        bindings.append((address, handler))
        return dummy

    monkeypatch.setattr(p3.http.server, 'ThreadingHTTPServer', fake_http)

    class NoThread:
        def __init__(self, **kw):
            pass

        def start(self):
            raise RuntimeError('fixed Thread.start failure')

    monkeypatch.setattr(p3.threading, 'Thread', NoThread)
    with pytest.raises(RuntimeError, match='Thread.start'):
        server.start()
    server.shutdown()
    assert closed == ['closed'] and server.srv is None
    assert bindings == [((want_address, 0), p3.P3Handler)]


@pytest.mark.parametrize('address', [None, '', 'localhost', '127.0.0.2', '::1', '[::]',
                                     '0.0.0.0:0', '100.110.162.4', '127.0.0.1\n'])
def test_server_rejects_nonliteral_bind_before_any_fixture_read_or_listen(monkeypatch, tmp_path, address):
    def unexpected_read(*a, **kw):
        pytest.fail('invalid bind must be rejected before fixture reads')

    monkeypatch.setattr(g, 'snapshot', unexpected_read)
    with pytest.raises(ValueError, match='must be literal 0.0.0.0 or 127.0.0.1'):
        p3.P3Server(tmp_path / 'site', tmp_path / 'data', bind_address=address)


@pytest.mark.parametrize('fault', ['clean', 'off_origin', 'same_origin'])
def test_actual_section_rows_stops_immediately_on_observed_destination(monkeypatch, tmp_path, fault):
    t, r, latch = target(), p3.new_receipt('fake', target()), g.StopLatch()
    r['sessions']['chromium'] = {}
    calls = []
    row = {'id': 'FAKE-1', 'ctx': 'A', 'acts': [], 'action': 'fixed clean observation', 'expected': {}}
    rows = [row, dict(row, id='FAKE-2')]

    async def call(session, code):
        calls.append(code)
        if code == p3.DRAIN:
            return {}
        if 'const CTXS =' in code:
            return {'contexts': {n: {'first_url': 'about:blank'} for n in ('A', 'B')},
                    'browser_type': 'chromium', 'browser_version': 'fake-1', 'distinct_contexts': True,
                    'observers_at': 'fixed', 'requests_before_navigation': 0}
        return {'obs': {'A': {}}, 'log': {} if fault == 'clean' else event(
            EXACT if fault == 'off_origin' else ORIGIN + '/unexpected')}

    monkeypatch.setattr(p3, '_call', call)
    ok = asyncio.run(p3.run_section(FakeTransport('chromium'), r, 'chromium', rows, t, tmp_path,
                                   'fake', tmp_path, 900, {}, 'fake:', {}, latch))
    assert ok == (fault == 'clean')
    assert len(r['steps']) == (2 if fault == 'clean' else 1)
    assert latch.tripped == (fault == 'off_origin')
    assert calls[-1] == p3.DRAIN


@pytest.mark.parametrize('fault', ['outer_cancel', 'CLOSE_cancel', 'bad_result'])
def test_cancellation_or_malformed_probe_cannot_skip_fallback(monkeypatch, fault):
    s, r, latch = FakeTransport('probe'), p3.new_receipt('fake', target()), g.StopLatch()
    reached, release = asyncio.Event(), asyncio.Event()

    @contextlib.asynccontextmanager
    async def transport(url):
        yield s

    async def call(session, code):
        if code == p3.CLOSE:
            if fault == 'CLOSE_cancel':
                raise asyncio.CancelledError
            if fault == 'outer_cancel':
                reached.set()
                await release.wait()
            return clean_close(['probe'])
        if code == p3.DRAIN:
            return event()
        return ['not an object'] if fault == 'bad_result' else {'type': 'webkit', 'log': {}}

    async def go():
        task = asyncio.create_task(p3.probe_session('fake:', 'fixed-probe', r=r, latch=latch, phase='probe'))
        if fault == 'outer_cancel':
            await reached.wait()
            task.cancel()
            release.set()
        if fault == 'bad_result':
            got = await task
            assert got['result_type'] == 'list'
        else:
            with pytest.raises(asyncio.CancelledError):
                await task

    monkeypatch.setattr(p3, 'open_session', transport)
    monkeypatch.setattr(p3, '_call', call)
    asyncio.run(go())
    assert s.browser_closes == 1 and latch.tripped
    assert r['log']['requests'][0]['url'] == EXACT
    if fault != 'outer_cancel':
        assert latch.blocked
